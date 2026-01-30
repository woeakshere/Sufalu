"""
Lightweight anime search module with Base64 decoding support.
"""
import asyncio
import re
import base64
import json
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from urllib.parse import urlparse, urljoin
import aiohttp
from selectolax.parser import HTMLParser

from config import SITES, SEARCH_PATTERNS, HEADERS

@dataclass(slots=True)
class SearchResult:
    """Memory-efficient search result container."""
    title: str
    url: str
    site: str
    year: Optional[str] = None
    episodes: Optional[int] = None

class AnimeSearcher:
    def __init__(self):
        self._session = None
        self.site_selectors = self._load_selectors()
    
    def _load_selectors(self) -> Dict[str, Dict[str, str]]:
        """Load CSS selectors for different sites."""
        return {
            'gogoanimes.cv': {
                'card': 'ul.items li',
                'title': 'p.name a',
                'link': 'p.name a',
                'year': 'p.released',
                'episodes': 'p.episode'
            },
            '9animetv.to': {
                'card': 'div.anime-list div.item',
                'title': 'div.detail h3 a',
                'link': 'div.detail h3 a',
                'year': 'div.detail span.type:contains("Released")',
            },
            'anikai.to': {
                'card': 'article.anime',
                'title': 'h3.title a',
                'link': 'h3.title a',
                'year': 'span.year'
            },
            # Add more site selectors as needed
        }
    
    @property
    async def session(self):
        """Lazy-load aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(
                headers=HEADERS,
                timeout=timeout
            )
        return self._session
    
    async def search(self, keyword: str, max_results: int = 10) -> List[SearchResult]:
        """
        Search anime across multiple sites with fallback.
        
        Args:
            keyword: Search term
            max_results: Maximum results to return
        
        Returns:
            List of SearchResult objects
        """
        results = []
        
        for site in SITES:
            for pattern in SEARCH_PATTERNS:
                if results:
                    break
                    
                search_url = f"https://{site}{pattern}{keyword.replace(' ', '+')}"
                
                try:
                    site_results = await self._search_site(search_url, site)
                    if site_results:
                        results.extend(site_results[:max_results])
                        break
                        
                except Exception as e:
                    print(f"Search failed for {site}: {e}")
                    continue
        
        return results[:max_results]
    
    async def _search_site(self, url: str, site: str) -> List[SearchResult]:
        """Search on a specific site."""
        session = await self.session
        
        try:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    return []
                
                html = await response.text()
                return self._parse_search_results(html, site, url)
                
        except Exception as e:
            print(f"Error searching {site}: {e}")
            return []
    
    def _parse_search_results(self, html: str, site: str, base_url: str) -> List[SearchResult]:
        """Parse search results from HTML."""
        parser = HTMLParser(html)
        results = []
        
        # Get selectors for this site
        selectors = self.site_selectors.get(site, {})
        card_selector = selectors.get('card', 'div.item, li.item, article')
        
        for card in parser.css(card_selector)[:15]:  # Limit to 15 cards
            try:
                # Extract title
                title_node = card.css_first(selectors.get('title', 'h3 a, h2 a, a.title'))
                if not title_node:
                    continue
                
                title = title_node.text(strip=True)
                if not title:
                    continue
                
                # Extract URL
                link_node = card.css_first(selectors.get('link', 'a'))
                href = link_node.attributes.get('href', '')
                if not href:
                    continue
                
                # Make URL absolute
                if href.startswith('/'):
                    url = f"https://{site}{href}"
                elif href.startswith('http'):
                    url = href
                else:
                    url = urljoin(base_url, href)
                
                # Extract additional info
                year = None
                if 'year' in selectors:
                    year_node = card.css_first(selectors['year'])
                    if year_node:
                        year_text = year_node.text(strip=True)
                        year_match = re.search(r'\d{4}', year_text)
                        if year_match:
                            year = year_match.group()
                
                episodes = None
                if 'episodes' in selectors:
                    ep_node = card.css_first(selectors['episodes'])
                    if ep_node:
                        ep_text = ep_node.text(strip=True)
                        ep_match = re.search(r'\d+', ep_text)
                        if ep_match:
                            episodes = int(ep_match.group())
                
                results.append(SearchResult(
                    title=title,
                    url=url,
                    site=site,
                    year=year,
                    episodes=episodes
                ))
                
            except Exception as e:
                print(f"Error parsing card: {e}")
                continue
        
        return results
    
    async def fetch_episode_links(self, anime_url: str) -> List[str]:
        """
        Extract episode links from anime series page.
        
        Args:
            anime_url: URL of anime series page
        
        Returns:
            List of episode URLs sorted by episode number
        """
        session = await self.session
        
        try:
            async with session.get(anime_url) as response:
                if response.status != 200:
                    return []
                
                html = await response.text()
                return self._parse_episode_links(html, anime_url)
                
        except Exception as e:
            print(f"Error fetching episodes: {e}")
            return []
    
    def _parse_episode_links(self, html: str, base_url: str) -> List[str]:
        """Parse episode links from HTML."""
        parser = HTMLParser(html)
        episodes = []
        
        # Common episode list selectors
        selectors = [
            'div.episode-list a',
            'ul.episodes li a',
            'div#episode_related a',
            'div.episodes a',
            'a[href*="episode"]'
        ]
        
        for selector in selectors:
            links = parser.css(selector)
            if links:
                for link in links:
                    href = link.attributes.get('href', '')
                    if href and ('episode' in href.lower() or 'ep-' in href.lower()):
                        # Make URL absolute
                        if href.startswith('/'):
                            parsed = urlparse(base_url)
                            episode_url = f"{parsed.scheme}://{parsed.netloc}{href}"
                        elif href.startswith('http'):
                            episode_url = href
                        else:
                            episode_url = urljoin(base_url, href)
                        
                        episodes.append(episode_url)
                
                if episodes:
                    break
        
        # Sort by episode number
        episodes.sort(key=lambda x: self._extract_episode_num(x))
        return episodes
    
    def _extract_episode_num(self, url: str) -> int:
        """Extract episode number from URL."""
        patterns = [
            r'episode-(\d+)',
            r'ep-(\d+)',
            r'/ep(\d+)',
            r'episode-(\d+)',
            r'/(\d+)/?$'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url.lower())
            if match:
                return int(match.group(1))
        
        return 0
    
    async def extract_m3u8(self, episode_url: str) -> Optional[str]:
        """Extract m3u8 URL from episode page with Base64 decoding."""
        session = await self.session
        
        retries = 3
        for attempt in range(retries):
            try:
                async with session.get(episode_url) as resp:
                    if resp.status != 200:
                        continue
                    
                    html = await resp.text()
                    
                    # Try direct patterns first
                    patterns = [
                        r'(https?://[^\s"\']+\.m3u8[^\s"\']*)',
                        r'file:\s*["\']([^"\']+\.m3u8[^\s"\']*)["\']',
                        r'video\.src\s*=\s*["\']([^"\']+\.m3u8[^\s"\']*)["\']',
                        r'src:\s*["\']([^"\']+\.m3u8[^\s"\']*)["\']',
                        r'data-video-src=["\']([^"\']+)["\']'
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, html, re.IGNORECASE)
                        if match:
                            url = match.group(1) if len(match.groups()) > 0 else match.group(0)
                            normalized = self._normalize_url(url, episode_url)
                            if normalized:
                                return normalized
                    
                    # Try Base64 encoded URLs
                    base64_patterns = [
                        r'atob\("([^"]+)"\)',
                        r'decode\("([^"]+)"\)',
                        r'data-value=["\']([A-Za-z0-9+/=]+)["\']'
                    ]
                    
                    for pattern in base64_patterns:
                        matches = re.findall(pattern, html)
                        for encoded in matches:
                            try:
                                decoded = base64.b64decode(encoded).decode('utf-8')
                                if '.m3u8' in decoded:
                                    m3u8_match = re.search(r'(https?://[^\s]+\.m3u8[^\s]*)', decoded)
                                    if m3u8_match:
                                        normalized = self._normalize_url(m3u8_match.group(1), episode_url)
                                        if normalized:
                                            return normalized
                            except:
                                continue
                    
                    # Try JSON data
                    json_pattern = r'(\{.*?"sources".*?\})'
                    json_matches = re.findall(json_pattern, html, re.DOTALL)
                    
                    for json_str in json_matches:
                        try:
                            data = json.loads(json_str)
                            
                            def find_m3u8(obj, depth=0):
                                if depth > 3:  # Prevent deep recursion
                                    return None
                                
                                if isinstance(obj, str) and '.m3u8' in obj:
                                    return obj
                                elif isinstance(obj, dict):
                                    for k, v in obj.items():
                                        if isinstance(k, str) and 'm3u8' in k.lower():
                                            return v if isinstance(v, str) else None
                                        result = find_m3u8(v, depth + 1)
                                        if result:
                                            return result
                                elif isinstance(obj, list):
                                    for item in obj:
                                        result = find_m3u8(item, depth + 1)
                                        if result:
                                            return result
                                return None
                            
                            url = find_m3u8(data)
                            if url:
                                normalized = self._normalize_url(url, episode_url)
                                if normalized:
                                    return normalized
                        except:
                            continue
                            
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
        
        return None
    
    def _normalize_url(self, url: str, base_url: str) -> str:
        """Convert relative URL to absolute."""
        if url.startswith('//'):
            return f'https:{url}'
        elif url.startswith('/'):
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}{url}"
        elif not url.startswith('http'):
            return urljoin(base_url, url)
        return url
    
    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

# Global instance
searcher = AnimeSearcher()