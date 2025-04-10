import asyncio
import os
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler
import requests
import json
import chromadb
import ollama
import logging
from langchain.text_splitter import RecursiveCharacterTextSplitter
import re

# Suppress ChromaDB logs
logging.getLogger('chromadb').setLevel(logging.ERROR)

def last_modified(url):
    """Check the last modified date of a URL."""
    response = requests.head(url)
    try:
        if "Last-Modified" in response.headers:
            return response.headers["Last-Modified"]
    except Exception:
        return None

def clean_text(html_content):
    """Convert HTML content to clean Markdown text with enhanced pattern removal."""
    soup = BeautifulSoup(html_content, 'html.parser')

    # Convert headers to Markdown
    for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        tag.insert_before(f"{'#' * int(tag.name[1])} {tag.get_text()}\n")
        tag.decompose()

    # Remove all anchor tags
    for tag in soup.find_all('a', href=True):
        tag.decompose()

    # Bold and italic
    for tag in soup.find_all('strong'):
        tag.insert_before(f"**{tag.get_text()}**")
        tag.decompose()

    for tag in soup.find_all('em'):
        tag.insert_before(f"*{tag.get_text()}*")
        tag.decompose()

    # Lists
    for tag in soup.find_all('ul'):
        tag.insert_before("\n")
        for li in tag.find_all('li'):
            li.insert_before(f"- {li.get_text()}\n")
        tag.decompose()

    # Paragraphs
    for tag in soup.find_all('p'):
        tag.insert_before(f"{tag.get_text()}\n\n")
        tag.decompose()

    text = soup.get_text()

    # First step: Normalize whitespace - this helps with consistent pattern matching
    text = re.sub(r'\s+', ' ', text)

    # Remove any raw URLs and Markdown-style links
    text = re.sub(r'https?://\S+', '', text)                    
    text = re.sub(r'www\.\S+', '', text)                        
    text = re.sub(r'\[.*?\]\s*https?://\S+', '', text)          
    text = re.sub(r'\[\s*\]', '', text)                         
    text = re.sub(r'\[.*?\]', '', text)                         

    # Remove specific phrases (case insensitive)
    text = re.sub(r'Last update:\s+\d{1,2}\s+\w+,?\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+CET.*?(?=\n|$)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Share this page with your colleagues.*?(?=\n|$)', '', text)
    

    exact_patterns = [
        r'Account Settings Logout',
        r'Account Settings Logout Filter:'
    ]
    
    # Apply exact pattern cleaning first, repeatedly until no more matches
    for pattern in exact_patterns:
        old_text = ""
        while old_text != text:
            old_text = text
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # 2. Then apply the more general patterns
    general_patterns = [
        r'Copy link',
        r'Thanks for sharing',
        r'Find any service',
        r'Share Buttons',
        r'Show all',
        r'52ViKING.*?help only',
        r'Administrator help only\s+Submit search',
        r'Day-to-day use help only',
        r'Copyright trademarks and disclaimer',
        r'All topics',
        r'Administrator help only',
        r'Submit search',
        r'Related:',
        r'Filter:'  
    ]
    
    # Apply each general pattern
    for pattern in general_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # Clean up any words ending with square bracket
    text = re.sub(r'(\w+)\]', r'\1', text)
    
    # Re-normalize whitespace after all the replacements
    text = re.sub(r'\s+', ' ', text)
    
    # Remove all special characters EXCEPT periods and some punctuation
    text = re.sub(r'[^\w\s\.\-\'\,\;\:\?]', '', text)
    
    return text.strip()

def embed_text(text, model="all-minilm"):
    """Generate an embedding for the given text using Ollama."""
    response = ollama.embed(model=model, input=text)
    return response["embeddings"][0]

def build_collection(collection_name="crawled_docs"):
    """Create or retrieve a ChromaDB collection."""
    db_path = os.path.join(os.getcwd(), "chroma_db")
    client = chromadb.PersistentClient(path=db_path)
    try:
        collection = client.get_collection(name=collection_name)
        print(f"Using existing database with {collection.count()} documents...")
        return collection
    except Exception:
        collection = client.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        print("Created new collection")
    return collection

async def get_urls_from_local_sitemap(sitemap_path):
    """Parse a local sitemap XML file to get a list of URLs."""
    try:
        tree = ET.parse(sitemap_path)
        root = tree.getroot()
        namespace = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = [loc.text for loc in root.findall('.//sm:loc', namespace)]
        return urls
    except Exception as e:
        print(f"Error parsing sitemap: {str(e)}")
        return []

async def crawl_and_embed_url(crawler, url, output_dir, collection):
    """Crawl a URL, clean content, save, split into chunks, embed, and store in ChromaDB."""
    try:
        last_mod_date = last_modified(url) or "Unknown"
        existing_data = collection.get(where={"url": url}, limit=1)
        
        if existing_data['metadatas'] and len(existing_data['metadatas']) > 0:
            existing_last_modified = existing_data['metadatas'][0].get('last_modified')
            if existing_last_modified == last_mod_date and last_mod_date != "Unknown":
                print(f"Skipping {url} - content unchanged (Last-Modified: {last_mod_date})")
                return
            else:
                print(f"Content changed for {url} (Old: {existing_last_modified}, New: {last_mod_date})")
                collection.delete(where={"url": url})
                print(f"Deleted previous version of {url} from database")
        
        result = await crawler.arun(url=url)
        cleaned_text = clean_text(result.markdown)

        filename = url.replace('://', '_').replace('/', '_').replace('?', '_').replace('&', '_')
        if len(filename) > 100:
            filename = filename[:100]
        filename = f"{filename}.md"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(cleaned_text)
        print(f"Saved: {url} -> {filepath}")
        
        # Using LangChain's RecursiveCharacterTextSplitter to split content
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1500,  
            chunk_overlap=750,  
            separators=["\n\n", "\n", ".", " ", ""]
        )
        content_chunks = splitter.split_text(cleaned_text)
        print(f"Split content into {len(content_chunks)} chunks")
        
        metadata = {"url": url, "last_modified": last_mod_date, "filename": filename}
        for i, chunk in enumerate(content_chunks):
            if not chunk.strip():
                continue
            embedding = embed_text(chunk)
            unique_id = f"{url}_{i}"
            chunk_metadata = {**metadata, "chunk_index": i, "chunk_total": len(content_chunks)}
            collection.add(
                ids=[unique_id],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[chunk_metadata]
            )
            print(f"Embedded chunk {i+1}/{len(content_chunks)} from {url}")
    except Exception as e:
        print(f"Error processing {url}: {str(e)}")

async def main_task():
    """Run the crawling and embedding process once."""
    sitemap_path = r"sitemap.xml"
    output_dir = "crawled_pages"
    os.makedirs(output_dir, exist_ok=True)
    metadata_file = os.path.join(output_dir, "url_metadata.json")
    
    url_metadata = {}
    if os.path.exists(metadata_file):
        with open(metadata_file, 'r', encoding='utf-8') as f:
            url_metadata = json.load(f)
        print(f"Loaded metadata for {len(url_metadata)} URLs")
    
    collection = build_collection()
    urls = await get_urls_from_local_sitemap(sitemap_path)
    print(f"Found {len(urls)} URLs in sitemap")
    
    async with AsyncWebCrawler() as crawler:
        tasks = [crawl_and_embed_url(crawler, url, output_dir, collection) for url in urls]
        batch_size = 6
        print(f"Processing URLs in batches of {batch_size}")
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            print(f"Processing batch {i//batch_size + 1}/{(len(tasks) + batch_size - 1)//batch_size}")
            await asyncio.gather(*batch)
    
    print(f"Crawling and embedding complete. Results saved to {output_dir}/ and vector database")
    
    all_items = collection.get(include=["metadatas"])
    for metadata in all_items["metadatas"]:
        if metadata and "url" in metadata and "last_modified" in metadata:
            url_metadata[metadata["url"]] = metadata["last_modified"]
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(url_metadata, f, ensure_ascii=False, indent=2)
    print(f"Updated metadata for {len(url_metadata)} URLs")

async def scheduler():
    """Background scheduler to run main_task every 6 hours."""
    while True:
        print("Starting new crawl cycle...")
        await main_task()
        print("Cycle complete. Sleeping for 6 hours...")
        await asyncio.sleep(6 * 3600)

if __name__ == "__main__":
    asyncio.run(scheduler())
