import { useState, useCallback, useEffect, useRef } from 'react';
import { getNews, getIndices, INDEX_SYMBOLS, fallbackIndex, normalizeIndexSymbol } from '../utils/api';
import { fetchMarketStatus } from '@/lib/marketUtils';

// Module-level caches (survive navigation, clear on page refresh)
// This caching is quite basic; a more robust solution like React Query would improve efficiency.
let newsCache = null;          // { items }
let indicesCache = null;       // [ index objects ]

/**
 * Formats a given timestamp to a relative time string (e.g. "just now", "10 min ago").
 * 
 * Future efficiency note: This could be memoized or handled by an internationalization 
 * library like date-fns, rather than computing it on the fly for every render.
 */
function formatRelativeTime(timestamp) {
  if (!timestamp) return '';
  const now = new Date();
  const then = new Date(timestamp);
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin} min ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} hr${diffHr > 1 ? 's' : ''} ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay} day${diffDay > 1 ? 's' : ''} ago`;
}

/**
 * useDashboardData Hook
 * Separates data fetching logic (news, indices, market status) out of Dashboard UI.
 * This makes the frontend codebase cleaner and shareable for iOS mobile client data services.
 */
export function useDashboardData() {
  const [indices, setIndices] = useState(() =>
    indicesCache || INDEX_SYMBOLS.map((s) => fallbackIndex(normalizeIndexSymbol(s)))
  );
  const [indicesLoading, setIndicesLoading] = useState(!indicesCache);

  const [newsItems, setNewsItems] = useState(() => newsCache?.items || []);
  const [newsLoading, setNewsLoading] = useState(!newsCache);

  const marketStatusRef = useRef(null);
  const [marketStatus, setMarketStatus] = useState(null);

  const fetchNews = useCallback(async () => {
    setNewsLoading(true);
    try {
      const data = await getNews({ limit: 50 });
      if (data.results && data.results.length > 0) {
        const mapped = data.results.map((r) => ({
          id: r.id,
          title: r.title,
          time: formatRelativeTime(r.published_at),
          isHot: r.has_sentiment,
          source: r.source?.name || '',
          favicon: r.source?.favicon_url || null,
          image: r.image_url || null,
          tickers: r.tickers || [],
        }));
        setNewsItems(mapped);
        newsCache = { items: mapped };
      }
    } catch {
      // Keep existing items on error; empty array if first load
    } finally {
      setNewsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!newsCache) fetchNews();
  }, [fetchNews]);

  const fetchIndices = useCallback(async () => {
    if (!indicesCache) setIndicesLoading(true);
    try {
      const { indices: next } = await getIndices(INDEX_SYMBOLS);
      setIndices(next);
      indicesCache = next;
    } catch (error) {
      console.error('[Dashboard] Error fetching indices:', error?.message);
      if (!indicesCache) {
        setIndices(INDEX_SYMBOLS.map((s) => fallbackIndex(normalizeIndexSymbol(s))));
      }
    } finally {
      setIndicesLoading(false);
    }
  }, []);

  // Adaptive polling: 30s during market hours, 60s during extended/closed
  useEffect(() => {
    const pollMarketStatus = () =>
      fetchMarketStatus()
        .then((s) => { 
          marketStatusRef.current = s; 
          setMarketStatus(s); 
        })
        .catch(() => {});
    
    pollMarketStatus();
    const statusId = setInterval(pollMarketStatus, 60000);
    return () => clearInterval(statusId);
  }, []);

  useEffect(() => {
    fetchIndices();
    let intervalId = null;
    const schedule = () => {
      const status = marketStatusRef.current;
      const isMarketOpen = status?.market === 'open' || 
                           (status && !status.afterHours && !status.earlyHours && status.market !== 'closed');
      
      const delay = isMarketOpen ? 30000 : 60000;
      intervalId = setTimeout(() => {
        // Efficiency note: Checking document.hidden prevents useless background fetches!
        if (!document.hidden) fetchIndices();
        schedule();
      }, delay);
    };
    schedule();
    
    return () => { 
      if (intervalId) clearTimeout(intervalId); 
    };
  }, [fetchIndices]);

  return { 
    indices, 
    indicesLoading, 
    newsItems, 
    newsLoading, 
    marketStatus, 
    marketStatusRef 
  };
}
