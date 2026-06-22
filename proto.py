import json
import requests
from helper import *
from bs4 import BeautifulSoup
from openai import OpenAI
from rag import *
from dotenv import load_dotenv
import os

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

BASE_URL = "https://www.stortinget.no"
WEB_HEARINGS_URL = "https://www.stortinget.no/no/Hva-skjer-pa-Stortinget/Horing/"

def fetch_hearings_from_api():
    url = "https://data.stortinget.no/eksport/horinger"

    params = {"format": "JSON"}
    
    response = requests.api.get(url, params=params)
    response.raise_for_status()

    data = response.json()

    hearings = data["horinger_liste"]

    normalized_hearings = [normalize_hearing(h) for h in hearings]

    written_hearings = [h for h in normalized_hearings if h["written"]] # Ignorerer muntlige høringer

    return written_hearings


def find_hearing_urls_from_web():
    response = requests.get(WEB_HEARINGS_URL)
    response.raise_for_status()

    html = response.text

    ids = set(re.findall(r"h=(\d+)", html))

    urls = [
        f"{BASE_URL}/no/Hva-skjer-pa-Stortinget/Horing/horing/?h={hearing_id}"
        for hearing_id in ids
    ]

    return sorted(urls)


def scrape_hearings_from_web(limit=None):
    urls = find_hearing_urls_from_web()

    if limit is not None:
            urls = urls[:limit]

    hearings = []

    for i, url in enumerate(urls, start=1):

        try:
            hearing = hearing_from_url(url)
            hearing["id"] = str(extract_hearing_id_from_url(url))
            hearing["source"] = "web"
            hearings.append(hearing)

        except Exception as e:
            print(f"Feil ved {url}: {e}")

        time.sleep(0.2)

    return hearings


def merge_hearings(api_hearings, web_hearings):
    merged = {}

    for hearing in api_hearings + web_hearings:
        key = str(hearing.get("id")).strip()

        if not key or key == "None":
            key = hearing.get("url")

        if key not in merged:
            merged[key] = hearing
        elif hearing.get("source") == "api":
            merged[key] = hearing

    return list(merged.values())


def fetch_hearings_from_stortinget():
    api_hearings = fetch_hearings_from_api()
    web_hearings = scrape_hearings_from_web()

    hearings = merge_hearings(api_hearings, web_hearings)

    return hearings


def load_known_hearing_ids():
    try:
        with open("data/known_hearings.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            return {str(id_) for id_ in data}
    except FileNotFoundError:
        return set()
    
    except json.JSONDecodeError:
        return set()

def save_known_hearings(ids):
    ids = {str(id_) for id_ in ids}

    with open("data/known_hearings.json", "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


def initialize_known_hearings(): # For første kjøring, for å bygge opp listen over kjente høringer
    hearings = fetch_hearings_from_stortinget()

    all_ids = {
        str(hearing["id"])
        for hearing in hearings
    }

    save_known_hearings(all_ids)

    print(f"Initialized known hearings with {len(all_ids)} hearings")


def find_new_hearings(hearings, known_ids):

    known_ids = {str(id_) for id_ in known_ids}

    return [
        hearing
        for hearing in hearings
        if str(hearing["id"]) not in known_ids
    ]


def get_hearing_content(hearing):
    response = requests.get(hearing["url"])
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    sections = soup.find_all("section")

    section_texts = []

    for section in sections:
        text = clean_text(section.get_text("\n", strip=True))

        if len(text) > 500:
            section_texts.append(text)

    if section_texts:
        page_text = max(section_texts, key=len)
    else:
        page_text = clean_text(soup.get_text("\n", strip=True))

    page_text = page_text[:12000]

    page_text = remove_stortinget_noise(page_text)

    return metadata_text(hearing) + "\n\nTekst fra Stortinget-siden:\n" + page_text


def load_position_document():
    with open("data/enkel_posisjons_dokument_2026.txt", "r") as f:
        return f.read()


def get_relevant_previous_responses(hearing_content):
    return retrieve_relevant_chunks(hearing_content, k=3)


def analyze_with_LLM(hearing_content, relevant_chunks=None):
    position_document = load_position_document()
    previous_responses_text = format_rag_context(relevant_chunks) if relevant_chunks else "Ingen relevante tidligere svar."

    prompt = f"""
    Du er en intern analyseassistent for arbeidsgiverforeningen Spekter.

    Oppgaven din er å gjøre en tidlig, grov vurdering av om en ny stortingshøring kan være relevant for Spekter eller Spekters medlemmer.

    Du skal IKKE skrive høringssvar. Du skal kun vurdere:
    - relevans for Spekter
    - relevans for Spekters medlemmer
    - foreslått ansvarlig avdeling
    - begrunnelse
    - anbefalt videre handling

    Tillatte avdelinger:
    - Samfunnspolitikk
    - Arbeidsliv
    - Forhandling
    - Økonomi

    Ikke foreslå andre avdelinger. Bruk null dersom ingen avdeling passer. Dersom en høring passer godt til to avdelinger skriver du begge to. Dette kan for eksempel være helse, som både passer for Arbeidsliv og Samfunnspolitikk.

    Veiledning for avdeling:
    - Samfunnspolitikk: helse, samferdsel, kultur, offentlig organisering, samfunnskritisk infrastruktur.
    - Arbeidsliv: arbeidsliv, arbeidsrett, tariff, arbeids- og sosialkomiteen, utdannings- og forskningskomiteen.
    - Økonomi: pensjon, finans, statsbudsjett, teknisk beregningsutvalg og økonomiske rammevilkår.
    - Forhandling: saker med direkte betydning for tariffoppgjør, forhandlingssystemer eller partsforhold.

    Spekters medlemsvirksomheter finnes blant annet innen:
    - Helse og omsorg: helseforetak, sykehus og spesialisthelsetjeneste.
    - Samferdsel og infrastruktur: Avinor, Vy, Flytoget, luftfart, jernbane og kollektivtransport.
    - Kultur og medier: NRK, teatre, orkestre, museer og kulturinstitusjoner.
    - Utdanning og forskning: universiteter, høyskoler, forskningsinstitutter og kunnskapsinstitusjoner.
    - Energi og samfunnskritisk infrastruktur: energiforsyning, teknisk infrastruktur og beredskap.
    - Statlige og offentlig finansierte virksomheter: Norsk Tipping, Vinmonopolet og virksomheter med særskilte samfunnsoppdrag.
    - Arbeidsinkludering og kompetanse: kompetanseutvikling, arbeidsinkludering og kvalifisering.


    Ikke marker en sak som relevant bare fordi den berører en sektor der Spekter har medlemmer.
    Saken bør være relevant for Spekter dersom den påvirker arbeidsgiverrollen, organisering, finansiering, styring, bemanning, kompetanse, tariff, arbeidsvilkår eller rammevilkår for medlemsvirksomhetene.

    Saker som primært gjelder etiske, medisinskfaglige eller partipolitiske spørsmål uten tydelig arbeidsgiver-, organisasjons- eller rammevilkårsdimensjon skal normalt vurderes som ikke relevante.
    Eksempler: abort, aktiv dødshjelp, bioteknologiske spørsmål og rene behandlingsfaglige spørsmål.

    Hvis saken kun indirekte berører en medlemssektor, men ikke tydelig berører Spekters rolle som arbeidsgiverforening, sett relevant=false eller relevance_score under 0.4.

    Viktige vurderingsregler:
    - Det er bedre å flagge en mulig relevant sak enn å filtrere bort en relevant sak.
    - Samtidig skal du være kritisk og ikke merke alt som relevant.
    - Hvis du er usikker, anbefal menneskelig vurdering.
    - Ikke finn på informasjon som ikke finnes i teksten.
    - Ignorer menytekst, navigasjon og teknisk tekst fra nettsiden.
    - Bruk tidligere høringssvar som støtte dersom de faktisk er relevante.
    - Dersom du viser til tidligere høringssvar, oppgi tittel og URL hvis tilgjengelig.
    - Eksempel på sak som normalt ikke er relevant: aktiv dødshjelp. Den kan berøre helsesektoren, men er ikke nødvendigvis relevant for Spekter som arbeidsgiverforening.

    Tidligere høringssvar er kun støtteinformasjon. Ikke vurder saken som relevant bare fordi tidligere høringssvar handler om samme brede sektor. Vurder om den nye saken har samme type arbeidsgiver-, styrings- eller rammevilkårsdimensjon.

    Posisjonsdokument:
    ```text
    {position_document}
    ```
    
    Tidligere relevante høringssvar:
    ```text
    {previous_responses_text}
    ```

    Ny høring:
    ```text
    {hearing_content}
    ```

    Returner KUN gyldig JSON.
    Ikke bruk markdown.
    Ikke pakk svaret inn i ```json.
    Ikke skriv tekst før eller etter JSON.
    Bruk null for ukjente eller ikke relevante verdier.
    relevance_score og confidence skal være desimaltall mellom 0 og 1.

    JSON-strukturen skal være nøyaktig slik:

    {{
    "relevant": true,
    "relevance_score": 0.87,
    "confidence": 0.95,
    "suggested_department": "Arbeidsliv",
    "affected_areas": ["Arbeidsrett", "Tariff"],
    "short_summary": "Sammendrag av høringen på maks 3 setninger.",
    "reasoning": "Kort begrunnelse for vurderingen.",
    "used_previous_responses": [
    {{
    "title": "Tittel på relevant tidligere høringssvar",
    "url": "URL hvis tilgjengelig",
    "why_relevant": "Kort forklaring."
    }}
    ],
    "recommended_action": "Menneskelig vurdering anbefales.",
    "crm_draft": {{
    "title": "Kort CRM-tittel",
    "source": "stortinget.no",
    "deadline": "Frist hvis oppgitt, ellers null",
    "responsible_department": "Arbeidsliv",
    "note": "Kort notat til eventuell CRM-registrering."
    }}
    }}
    """

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content


def save_analysis_result(hearing, analysis):
    try:
        with open("data/analysis_results.json", "r") as f:
            results = json.load(f)
    except FileNotFoundError:
        results = []

    results.append({"hearing_id": hearing["id"], "url": hearing["url"], "analysis": analysis})

    try:
        with open("data/analysis_results.json", "w") as f:
            json.dump(results, f)
    except Exception as e:
        print(f"Error saving analysis result: {e}")
    
    return


def get_analyses(hearingid):
    analyses = []

    try:
        with open("data/analysis_results.json", "r") as f:
            results = json.load(f)

    except FileNotFoundError:
        results = []

    for result in results:

        if result["hearing_id"] == hearingid:
                analyses.append(result["analysis"])

    return analyses


def update_known_hearings(hearings):
    known_ids = set(load_known_hearing_ids())
    current_ids = {
        str(hearing["id"])
        for hearing in hearings
    }

    updated_ids = known_ids.union(current_ids)

    added = len(updated_ids) - len(known_ids)

    save_known_hearings(updated_ids)

    if added == 0:
        print(f"Ingen nye høringer. ({len(updated_ids)} kjente høringer)")
    else:
        print(
            f"Fant {added} nye høringer. "
            f"({len(updated_ids)} kjente høringer totalt)"
        )


def get_hearing_analysis_by_url(url): # for å teste de høringene som ikke mottas av API-et
    hearing = hearing_from_url(url)

    raw_content = get_hearing_content(hearing)
    hearing["raw"] = raw_content
    content = metadata_text(hearing) + "\n\n" + hearing["raw"]

    relevant_chunks = retrieve_relevant_chunks(content, k=3)
    analysis = analyze_with_LLM(content, relevant_chunks) # Legg til eller fjern relevant_chunks for å teste med/uten RAG

    return hearing, analysis, relevant_chunks


def main():

    known_hearings = load_known_hearing_ids()

    hearings = fetch_hearings_from_stortinget()

    if not known_hearings:
            initialize_known_hearings()
            print("Første kjøring: lagrer eksisterende høringer som kjent.")

    new_hearings = find_new_hearings(hearings, known_hearings)

    print("\nNye høringer:")
    for h in new_hearings:
        print(h["id"], h["source"], h["title"])

    for hearing in new_hearings:

        content = get_hearing_content(hearing)

        print("Analyseres av LLM ...")

        relevant_chunks = retrieve_relevant_chunks_unique_docs(content, k=3)

        analysis = analyze_with_LLM(content, relevant_chunks)

        save_analysis_result(hearing, analysis)

        pretty_print_analysis(hearing, analysis, relevant_chunks)

    update_known_hearings(hearings)

    return



if __name__ == "__main__":
    main()