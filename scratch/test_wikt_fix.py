import requests
import json

def test_wiktionary_prefix():
    url = "http://127.0.0.1:8000/api/ending_search"
    payload = {
        "ending": "а",
        "search_type": "prefix",
        "pos": "ANY",
        "source": "wiktionary",
        "page": 1,
        "page_size": 50,
        "word_filter": ""
    }
    
    print(f"Testing {payload['source']} {payload['search_type']} search for '{payload['ending']}'...")
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        
        results = data.get("results", {})
        total = data.get("total", 0)
        shown = data.get("pagination", {}).get("shown", 0)
        
        print(f"Total results: {total}")
        print(f"Shown results: {shown}")
        
        if results:
            print("Results keys (POS):", list(results.keys()))
            for p in list(results.keys())[:2]:
                print(f"Sample {p}: {results[p][:5]}")
        else:
            print("ERROR: Results dictionary is empty!")
            
    except Exception as e:
        print(f"Error during request: {e}")

if __name__ == "__main__":
    test_wiktionary_prefix()
