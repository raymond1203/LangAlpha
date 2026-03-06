import { useState, useEffect, useRef, useCallback } from 'react';
import { fetchStockQuote, fetchCompanyOverview, fetchAnalystData } from '../utils/api';
import { fetchMarketStatus } from '@/lib/marketUtils';

/**
 * useStockData Hook
 * 
 * Extracts data fetching logic out of MarketView to improve modularity.
 * Manages fetching of stock quotes, company overview, analyst data (targets/grades),
 * and the polling of market status.
 * 
 * Future efficiency note: Implementing a data-fetching library (e.g. React Query / SWR)
 * would automatically handle the AbortControllers, polling intervals, and cache invalidation
 * used here, making this codebase considerably leaner.
 */
export function useStockData({
    selectedStock,
    wsStatus,
    setPreviousClose,
    setDayOpen
}) {
    const [stockInfo, setStockInfo] = useState(null);
    const [realTimePrice, setRealTimePrice] = useState(null);
    const [snapshotData, setSnapshotData] = useState(null);

    const [overviewData, setOverviewData] = useState(null);
    const [overviewLoading, setOverviewLoading] = useState(false);
    const [overlayData, setOverlayData] = useState(null);
    const [marketStatus, setMarketStatus] = useState(null);

    // Consolidated fetch: stockInfo + realTimePrice from a single API call
    // with AbortController and Page Visibility API.
    // When WS is connected, only fetch once (for stockInfo/name/exchange) — skip polling.
    useEffect(() => {
        if (!selectedStock) return;

        const abortController = new AbortController();

        const loadStockQuote = async () => {
            try {
                const { stockInfo: info, realTimePrice: price, snapshot } = await fetchStockQuote(
                    selectedStock,
                    { signal: abortController.signal }
                );
                setStockInfo(info);
                if (price) setRealTimePrice(price);
                // Seed WS refs from snapshot for accurate change% calculation
                if (snapshot) {
                    setSnapshotData(snapshot);
                    if (snapshot.previous_close != null && setPreviousClose) setPreviousClose(selectedStock, snapshot.previous_close);
                    if (snapshot.open != null && setDayOpen) setDayOpen(selectedStock, snapshot.open);
                }
            } catch (error) {
                if (error?.name === 'CanceledError' || error?.name === 'AbortError') return;
                console.error('Error loading stock quote:', error);
                setStockInfo({
                    Symbol: selectedStock,
                    Name: `${selectedStock} Corp`,
                    Exchange: 'NASDAQ',
                });
            }
        };

        loadStockQuote();

        // Suppress 60s polling when WS is connected — WS provides sub-second updates
        if (wsStatus === 'connected') {
            return () => abortController.abort();
        }

        // Refresh price every 60s, but skip when tab is hidden (Page Visibility API)
        let cancelled = false;
        const priceInterval = setInterval(async () => {
            if (document.hidden) return; // Skip fetch when tab is not visible
            try {
                const { stockInfo: info, realTimePrice: price, snapshot } = await fetchStockQuote(selectedStock);
                if (cancelled) return;
                setStockInfo(info);
                if (price) setRealTimePrice(price);
                if (snapshot) {
                    setSnapshotData(snapshot);
                    if (snapshot.previous_close != null && setPreviousClose) setPreviousClose(selectedStock, snapshot.previous_close);
                    if (snapshot.open != null && setDayOpen) setDayOpen(selectedStock, snapshot.open);
                }
            } catch (error) {
                console.error('Error refreshing stock quote:', error);
            }
        }, 60000);

        return () => {
            cancelled = true;
            abortController.abort();
            clearInterval(priceInterval);
        };
    }, [selectedStock, wsStatus, setPreviousClose, setDayOpen]);

    // Fetch company overview data
    useEffect(() => {
        if (!selectedStock) return;
        const ac = new AbortController();
        setOverviewLoading(true);
        fetchCompanyOverview(selectedStock, { signal: ac.signal })
            .then((result) => {
                setOverviewData(result);
            })
            .catch((err) => {
                if (err?.name === 'CanceledError' || err?.name === 'AbortError') return;
                console.error('Error fetching company overview:', err);
                setOverviewData(null);
            })
            .finally(() => setOverviewLoading(false));
        return () => ac.abort();
    }, [selectedStock]);

    // Fetch analyst data (price targets + grades) for chart overlays
    useEffect(() => {
        if (!selectedStock) return;
        const ac = new AbortController();
        fetchAnalystData(selectedStock, { signal: ac.signal })
            .then((analyst) => {
                setOverlayData(analyst ? {
                    priceTargets: analyst.priceTargets || null,
                    grades: analyst.grades || [],
                } : null);
            })
            .catch((err) => {
                if (err?.name === 'CanceledError' || err?.name === 'AbortError') return;
                setOverlayData(null);
            });
        return () => ac.abort();
    }, [selectedStock]);

    // Poll market status (60s interval)
    useEffect(() => {
        const loadStatus = () => fetchMarketStatus().then(setMarketStatus).catch(() => { });
        loadStatus();
        const id = setInterval(() => { if (!document.hidden) loadStatus(); }, 60000);
        return () => clearInterval(id);
    }, []);

    // Handler for latest WS bar data, updating the realtime price
    const stockInfoRef = useRef(stockInfo);
    useEffect(() => { stockInfoRef.current = stockInfo; }, [stockInfo]);

    const handleLatestBar = useCallback((bar) => {
        if (!bar?.close) return;
        setRealTimePrice((prev) => {
            if (!prev || !prev.price) return prev;
            const updatedPrice = Math.round(bar.close * 100) / 100;
            // Use previousClose from snapshot if available, else derive from initial quote
            const previousClose = prev.previousClose ?? ((prev.price ?? 0) - (prev.change ?? 0));
            if (!previousClose) {
                // Still update price even without previousClose — just skip change% recalculation
                return { ...prev, price: updatedPrice, close: bar.close, timestamp: bar.time * 1000 };
            }
            const change = bar.close - previousClose;
            const changePct = parseFloat(((change / previousClose) * 100).toFixed(2));
            return {
                ...prev,
                price: updatedPrice,
                close: bar.close,
                change: Math.round(change * 100) / 100,
                changePercent: changePct,
                timestamp: bar.time * 1000,
            };
        });
    }, []);

    return {
        stockInfo,
        setStockInfo,
        realTimePrice,
        setRealTimePrice,
        snapshotData,
        setSnapshotData,
        overviewData,
        overviewLoading,
        overlayData,
        marketStatus,
        handleLatestBar
    };
}
