import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
import requests


def normalize_hearing(raw):

    sak_info_liste = raw.get("horing_sak_info_liste", [])
    sak_info = sak_info_liste[0] if sak_info_liste else {}

    komite = raw.get("komite") or {}

    return {
        "id": raw.get("id"),
        "title": sak_info.get("sak_tittel") or sak_info.get("sak_korttittel"),
        "committee": komite.get("navn"),
        "deadline": parse_stortinget_date(raw.get("innspillsfrist")
            or raw.get("anmodningsfrist_dato_tid") or raw.get("soknadsfrist_dato_tid")),
        "date": parse_stortinget_date(raw.get("start_dato")),
        "url": normalize_url(sak_info.get("sak_publikasjon")),
        "raw": raw,
        "status": raw.get("horing_status"),
        "written": raw.get("skriftlig"),
        "case_reference": sak_info.get("sak_henvisning"),
        "case_id": sak_info.get("sak_id"),
        "source":"api"
    }


def normalize_url(url):
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    return url

def extract_stortinget_title(soup):
    banned_titles = {
        "Stortinget.no",
        "Søk",
        "Høring",
        "Høringer",
    }

    # 1. Prøv h1-er som ikke er meny/globaltittel
    for h1 in soup.find_all("h1"):
        text = h1.get_text(" ", strip=True)

        if text and text not in banned_titles and len(text) > 20:
            return text

    # 2. Prøv meta title
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()

        if title not in banned_titles and len(title) > 20:
            return title

    # 3. Prøv vanlig title-tag
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(" ", strip=True)
        title = title.replace(" - stortinget.no", "").strip()
        title = title.replace(" - Stortinget", "").strip()

        if title not in banned_titles:
            return title

    return None

def parse_stortinget_date(date_string):
    if not date_string:
        return None
    
    match = re.match(r"/Date\((\d+)([+-]\d{4})?\)/", date_string)

    if not match:
        return date_string

    timestamp_ms = int(match.group(1))
    timestamp_s = timestamp_ms / 1000

    return datetime.fromtimestamp(timestamp_s).isoformat()


def clean_text(text):
    banned_lines = {
        "Stortinget.no",
        "Del",
        "Facebook",
        "X/Twitter",
        "E-post",
        "Skriv ut",
        "Meld feil",
        "Gå til alle temaer",
        "Gå til saker",
    }

    lines = []

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        if line in banned_lines:
            continue

        if "Du bruker en gammel nettleser" in line:
            continue

        lines.append(line)

    return "\n".join(lines)


def metadata_text(hearing):
    return f"""
        Tittel: {hearing.get("title")}
        Komité: {hearing.get("committee")}
        Saksreferanse: {hearing.get("case_reference")}
        Frist: {hearing.get("deadline")}
        Dato: {hearing.get("date")}
        URL: {hearing.get("url")}
        """.strip()


def remove_stortinget_noise(text):
    markers = [
        "Innstilling fra",
        "Representantforslag",
        "Prop.",
        "Til Stortinget",
        "Innhold"
    ]

    for marker in markers:
        index = text.find(marker)
        if index != -1:
            return text[index:]

    return text


def clean_json_string(text):
    text = text.strip()

    # Fjerner ```json ... ``` eller ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    return text.strip()


def parse_analysis(analysis):
    if isinstance(analysis, list):
        analysis = analysis[0]

    if isinstance(analysis, dict):
        return analysis

    if isinstance(analysis, str):
        cleaned = clean_json_string(analysis)
    
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            print("\nJSON parsing feilet")
            print(f"Feil: {e}")
            print("\nModelloutput:")
            print(cleaned)
            raise

    raise TypeError(f"Uventet type: {type(analysis)}")


def normalize_id(value):
    return str(value).strip()

def extract_hearing_id_from_url(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    if "h" in query:
        return query["h"][0]

    return None


def pretty_print_analysis(hearing, analysis, relevant_chunks=None):

    analysis = parse_analysis(analysis)

    """
    analysis kan være:
    - JSON-string
    - liste med én JSON-string
    - dictionary
    """

    if isinstance(analysis, list):
        analysis = analysis[0]

    if isinstance(analysis, str):
        analysis = json.loads(analysis)

    print("\n" + "=" * 80)
    print(f"HØRINGSANALYSE")
    print("=" * 80)

    print(f"Tittel: {hearing.get('title')}")
    print(f"URL: {hearing.get('url')}")
    print(f"Frist: {hearing.get('deadline')}")
    print(f"Komité: {hearing.get('committee')}")

    print()
    print(f"Relevant:              {analysis['relevant']}")
    print(f"Relevansscore:         {analysis['relevance_score']}")
    print(f"Konfidens:             {analysis['confidence']}")
    print(f"Foreslått avdeling:    {analysis['suggested_department']}")

    print("\nBerørte områder:")
    for area in analysis["affected_areas"]:
        print(f"  • {area}")

    print("\nKort sammendrag:")
    print(analysis["short_summary"])

    print("\nBegrunnelse:")
    print(analysis["reasoning"])

    print("\nAnbefalt handling:")
    print(analysis["recommended_action"])

    if relevant_chunks:
        print("\nMest relevante tidligere høringssvar brukt som kontekst:")
        for i, chunk in enumerate(relevant_chunks, start=1):
            print(f"\n{i}. {chunk['title']}")
            print(f"   Score: {chunk['score']:.3f}")
            print(f"   URL: {chunk['url']}")

    crm = analysis["crm_draft"]

    print("\nCRM-utkast")
    print("-" * 80)
    print(f"Tittel:               {crm['title']}")
    print(f"Kilde:                {crm['source']}")
    print(f"Frist:                {crm['deadline']}")
    print(f"Ansvarlig avdeling:   {crm['responsible_department']}")

    print("\nNotat:")
    print(crm["note"])

    print("\n" + "=" * 80)
    return


def hearing_from_url(url):
    response = requests.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    title = extract_stortinget_title(soup)

    return {
        "id": str(url.split("h=")[-1]),
        "title": title,
        "committee": None,
        "deadline": None,
        "date": None,
        "url": url,
        "raw": None,
        "status": None,
        "written": None,
        "case_reference": None,
        "case_id": None,
        "source": "web"
    }
