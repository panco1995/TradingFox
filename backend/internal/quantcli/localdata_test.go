package quantcli

import (
	"context"
	"encoding/json"
	"testing"
	"time"
)

// TestKlinesAgainstLocalData exercises the real Python CLI over the local
// Parquet store. It is skipped automatically when no data is present.
func TestKlinesAgainstLocalData(t *testing.T) {
	client, err := Default()
	if err != nil {
		t.Skipf("python not configured: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()

	payload, err := client.Klines(ctx, KlineQuery{
		Symbol: "BTCUSDT", Interval: "1w", Days: 365, Limit: 500,
	})
	if err != nil {
		t.Fatalf("klines: %v", err)
	}
	var doc struct {
		Interval   string `json:"interval"`
		Count      int    `json:"count"`
		Aggregated bool   `json:"aggregated"`
		Bars       []struct {
			T      string  `json:"t"`
			C      float64 `json:"c"`
			Closed *bool   `json:"closed"`
		} `json:"bars"`
	}
	if err := json.Unmarshal(payload, &doc); err != nil {
		t.Fatal(err)
	}
	if doc.Count == 0 {
		t.Skip("no local 1m data for BTCUSDT")
	}
	if doc.Interval != "1w" || !doc.Aggregated {
		t.Fatalf("doc = %+v", doc)
	}
	if doc.Bars[len(doc.Bars)-1].Closed == nil {
		t.Fatal("aggregated bars must report closed")
	}
	t.Logf("weekly bars=%d last=%s close=%.2f", doc.Count, doc.Bars[len(doc.Bars)-1].T, doc.Bars[len(doc.Bars)-1].C)

	symbols, err := client.KlineSymbols(ctx, "1w")
	if err != nil {
		t.Fatalf("symbols: %v", err)
	}
	if !json.Valid(symbols) {
		t.Fatalf("symbols = %s", symbols)
	}
	t.Logf("symbols=%s", symbols)
}
