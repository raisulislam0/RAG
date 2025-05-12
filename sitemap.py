import requests
from bs4 import BeautifulSoup
import urllib.parse as UP
import xml.etree.ElementTree as ET
import xml.dom.minidom
from time import sleep

class SitemapGenerator:
    def __init__(self, start_url, output_file="sitemap.xml"):
        self.start_url = start_url
        self.output_file = output_file
        self.base_url = self._get_base_url(start_url)
        self.visited_urls = set()
        self.sitemap_urls = []
        self.domain = UP.urlparse(start_url).netloc
        
    def _get_base_url(self, url):
        """Extract the base URL (scheme + domain)"""
        parsed = UP.urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    
    def _normalize_url(self, url, parent_url):
        """Normalize URLs to absolute format"""
        if not url:
            return None
            
        # Skip non-HTTP URLs and anchors
        if url.startswith(('mailto:', 'tel:', 'javascript:')) or url.startswith('#'):
            return None
            
        # Convert to absolute URL
        if not url.startswith(('http://', 'https://')):
            return UP.urljoin(parent_url, url)
        
        return url
        
    def _is_valid_url(self, url):
        """Check if URL is valid and in the same domain"""
        if not url:
            return False
            
        parsed = UP.urlparse(url)
        
        if parsed.netloc != self.domain:
            return False
            
        ignored_extensions = ['.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.png', '.jpg', '.jpeg', '.gif', '.zip', '.tar', '.gz', '.xml']
        if any(url.lower().endswith(ext) for ext in ignored_extensions):
            return False
            
        ignored_patterns = ['logout', 'login', 'sign-in', 'sign-out', 'search', 'print']
        if any(pattern in url.lower() for pattern in ignored_patterns):
            return False
            
        return True
        
    def crawl(self, max_pages=1000):
        """Crawl the website and collect URLs"""
        print(f"Starting crawl from {self.start_url}")
        
        self.visited_urls = set()
        self.sitemap_urls = []
        
        queue = [self.start_url]
        pages_crawled = 0
        
        while queue and pages_crawled < max_pages:
            url = queue.pop(0)
            
            if url in self.visited_urls:
                continue
                
            self.visited_urls.add(url)
            
            try:        
                
                print(f"Crawling: {url}")
                response = requests.get(url, timeout=10)
                
                content_type = response.headers.get('Content-Type', '')
                if 'text/html' not in content_type.lower():
                    continue
                    
                if url != self.start_url:
                    self.sitemap_urls.append(url)
                    pages_crawled += 1
                
                soup = BeautifulSoup(response.text, 'html.parser')

                for link in soup.find_all('a', href=True):
                    href = link['href']
                    normalized_url = self._normalize_url(href, url)
                    
                    if normalized_url and self._is_valid_url(normalized_url) and normalized_url not in self.visited_urls:
                        queue.append(normalized_url)
                        
            except Exception as e:
                print(f"Error crawling {url}: {e}")
                
        print(f"Crawl complete. Discovered {len(self.sitemap_urls)} pages.")
        
    def generate_sitemap(self):
        """Generate the sitemap XML"""
        print("Generating sitemap.xml...")
        
        urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
        
        for url in self.sitemap_urls:
            url_element = ET.SubElement(urlset, "url")
            
            loc = ET.SubElement(url_element, "loc")
            loc.text = url
            
        xml_str = ET.tostring(urlset, encoding="utf-8")
        dom = xml.dom.minidom.parseString(xml_str)
        pretty_xml = dom.toprettyxml(indent="  ")
        
        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
            
        print(f"Sitemap generated and saved to {self.output_file}")
        
    def run(self, max_pages=1000):
        """Run the sitemap generator"""
        self.crawl(max_pages)
        self.generate_sitemap()

def scheduler():
    """Run the sitemap generation process every 6 hours."""
    start_url = "https://help.fiftytwo.com/help/en-us/Content/Home.htm"
    while True:
        print("Starting sitemap generation cycle...")
        generator = SitemapGenerator(start_url)
        generator.run(max_pages=500)  
        print("Sitemap generation cycle complete. Sleeping for 6 hours...\n")
        sleep(6 * 3600)

if __name__ == "__main__":
    scheduler()
