import asyncio
import shutil
import os
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler
import requests
import logging
from langchain.text_splitter import RecursiveCharacterTextSplitter
import re
from processor import build_collection, embed_text
from time import time

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
    text = re.sub(r'\[.*?\]', '', text) #non-greedy match [first] and [second]                        

    text = re.sub(r'Last update:\s+\d{1,2}\s+\w+,?\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+CET.*?(?=\n|$)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Share this page with your colleagues.*?(?=\n|$)', '', text)
    

    exact_patterns = [
        r'Account Settings Logout',
        r'Account Settings Logout Filter:'
    ]
    
    for pattern in exact_patterns:
        old_text = ""
        while old_text != text:
            old_text = text
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
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
    """Crawl a URL, clean content, split into chunks, embed, and store in ChromaDB."""
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

        # Create a temporary file for processing
        filename = url.replace('://', '_').replace('/', '_').replace('?', '_').replace('&', '_')
        if len(filename) > 100:
            filename = filename[:100]
        filename = f"{filename}.md"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(cleaned_text)
        print(f"Processing: {url}")
        
        # Using LangChain's RecursiveCharacterTextSplitter to split content
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=2000,  
            chunk_overlap=400,  
            separators=["\n\n", "\n", ".", " ", ""]
        )
        content_chunks = splitter.split_text(cleaned_text)
        print(f"Split content into {len(content_chunks)} chunks")
        
        metadata = {"url": url, "last_modified": last_mod_date}
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
            
        # Remove the temporary file after processing
        if os.path.exists(filepath):
            os.remove(filepath)
            
    except Exception as e:
        print(f"Error processing {url}: {str(e)}")

async def main_task():
    """Run the crawling and embedding process once."""
    sitemap_path = r"sitemap.xml"
    output_dir = "crawled_pages"
    os.makedirs(output_dir, exist_ok=True)
    
    collection = build_collection()
    urls = await get_urls_from_local_sitemap(sitemap_path)
    print(f"Found {len(urls)} URLs in sitemap")
    
    async with AsyncWebCrawler() as crawler:
        tasks = [crawl_and_embed_url(crawler, url, output_dir, collection) for url in urls]
        print(f"Processing {len(tasks)} URLs concurrently")
        await asyncio.gather(*tasks)
        
    print(f"Crawling and embedding complete. Vector database updated.")
    
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
        

async def scheduler():
    """Background scheduler to run main_task every 6 hours."""
    while True:
        start_time = time()
        print("Starting new crawl cycle...")
        await main_task()
        print(time() - start_time)
        print("Cycle complete. Sleeping for 1 hour...")
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(scheduler())
