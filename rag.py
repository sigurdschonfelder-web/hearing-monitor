import json
import time
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import requests
from helper import clean_text
from openai import OpenAI
import numpy as np
import os

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SITEMAP_URL = "https://spekter.no/sitemap.xml"

client = OpenAI(api_key=OPENAI_API_KEY)

def get_sitemap_urls():
    response = requests.get(SITEMAP_URL)
    response.raise_for_status()

    root = ET.fromstring(response.content)

    urls = []

    for elem in root.iter():
        if elem.tag.endswith("loc") and elem.text:
            urls.append(elem.text.strip())

    return [url for url in urls if "/spekter-mener/horingssvar/" in url]


def extract_article(url):
    response = requests.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    title_tag = soup.find("h1")
    title = extract_title(soup)

    # Prøv typiske hovedcontainere først
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.body
    )

    text = clean_text(main.get_text("\n", strip=True)) if main else ""

    return {
        "title": title,
        "url": url,
        "text": text
    }


def scrape_hearing_responses(limit=None):
    hearing_urls = get_sitemap_urls()

    # print("Antall artikler:", len(hearing_urls))

    # inspect_aricle(hearing_urls[1])

    if limit:
        hearing_urls = hearing_urls[:limit]

    articles = []

    for i, url in enumerate(hearing_urls, start=1):
        print(f"[{i}/{len(hearing_urls)}] Henter {url}")

        try:
            article = extract_article(url)
            articles.append(article)

        except Exception as e:
            print(f"Feil ved {url}: {e}")

        time.sleep(0.5)  # vær snill mot nettsiden

    return articles


def save_articles(articles):
    with open("data/previous_hearing_responses.json", "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)


def chunk_text(text, max_chars=1500, overlap=200):
    chunks = []
    start = 0

    while start < len(text):
        end = start + max_chars

        if end < len(text):
            while end < len(text) and text[end] != " ":
                end += 1

        chunk = text[start:end]
        chunks.append(chunk.strip())

        start = end - overlap

    return chunks


def create_chunks(input_file="data/previous_hearing_responses.json"):
    with open(input_file, "r", encoding="utf-8") as f:
        articles = json.load(f)

    all_chunks = []

    for article_index, article in enumerate(articles):
        title = article["title"]
        url = article["url"]
        text = article["text"]

        chunks = chunk_text(text)

        for chunk_index, chunk in enumerate(chunks):
            all_chunks.append({
                "article_index": article_index,
                "chunk_index": chunk_index,
                "title": title,
                "url": url,
                "text": f"""
Tittle: {title}
URL: {url}

Tekst: 
{chunk}
""".strip()
            })
    
    return all_chunks
        

def load_chunks(path="data/hearing_response_chunks.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
    

def save_chunks(chunks, path="data/hearing_response_embeddings.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False)


def embed_texts(texts, model="text-embedding-3-small"):
    response = client.embeddings.create(
        model=model,
        input=texts
    )
    return [item.embedding for item in response.data]

def embed_chunks(input_file="data/hearing_response_chunks.json",
                 output_file="data/hearing_response_embeddings.json",
                 batch_size=50):
    
    chunks = load_chunks(input_file)

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]

        texts = [
            chunk["text"] for chunk in batch
        ]

        print(f"Embedder {i + 1}–{i + len(batch)} av {len(chunks)}")

        embeddings = embed_texts(texts)

        for chunk, embedding in zip(batch, embeddings):
            chunk["embedding"] = embedding

    save_chunks(chunks, output_file)

    print(f"Lagret {len(chunks)} chunks med embeddings i {output_file}")


def inspect_aricle(url):
    response = requests.get(url)
    response.raise_for_status()

    print("URL:", repr(url))
    print("TYPE", type(url))

    soup = BeautifulSoup(response.text, "html.parser")

    print("H1:")
    for h1 in soup.find_all("h1"):
        print(repr(h1.get_text(" ", strip=True)))

    print("\nOG title:")
    og = soup.find("meta", property="og:title")
    print(og.get("content") if og else None)

    print("\nTitle tag:")
    title = soup.find("title")
    print(title.get_text(" ", strip=True) if title else None)


def extract_title(soup):
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)

    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()

    title = soup.find("title")
    if title and title.get_text(strip=True):
        return title.get_text(" ", strip=True).replace(" - Spekter", "").strip()

    return None

def load_embedded_chunks(path="data/hearing_response_embeddings.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def embed_query(query, model="text-embedding-3-small"):
    response = client.embeddings.create(
        model=model,
        input=query
    )

    return response.data[0].embedding

def cosine_similarity(a,b):
    a = np.array(a)
    b = np.array(b)

    return np.dot(a,b) / (
        np.linalg.norm(a) * np.linalg.norm(b)
    )
    
def retrieve_relevant_chunks(query, k=5, embeddings_file="data/hearing_response_embeddings.json"):
    chunks = load_embedded_chunks(embeddings_file)
    query_embedding = embed_query(query)

    scored_chunks = []

    for chunk in chunks:
        score = cosine_similarity(
            query_embedding,
            chunk["embedding"]
        )

        scored_chunks.append({
            "score": score,
            "title": chunk["title"],
            "url": chunk["url"],
            "chunk_index": chunk["chunk_index"],
            "text": chunk["text"]
        })

    scored_chunks.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return scored_chunks[:k]

def retrieve_relevant_chunks_unique_docs(query, k=3):
    chunks = retrieve_relevant_chunks(query, k=20)

    seen_urls = set()
    unique = []

    for chunk in chunks:
        url = chunk["url"]

        if url in seen_urls:
            continue

        seen_urls.add(url)
        unique.append(chunk)

        if len(unique) == k:
            break
    return unique


def format_rag_context(relevant_chunks):
    parts = []

    for i, chunk in enumerate(relevant_chunks, start=1):
        parts.append(f"""
Tidligere høringssvar {i}
Tittel: {chunk["title"]}
URL: {chunk["url"]}
Relevansscore: {chunk["score"]:.3f}

Utdrag:
{chunk["text"]}
""".strip())

    return "\n\n---\n\n".join(parts)

