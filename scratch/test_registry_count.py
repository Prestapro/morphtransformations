import requests

def test_registry_count():
    url = "http://127.0.0.1:8000/api/ending_search"
    
    payload = {
        "ending": "*",
        "search_type": "root",
        "source": "algorithmic",
        "include_proper": False
    }
    resp = requests.post(url, json=payload)
    data = resp.json()
    print(f"Keys: {list(data.keys())}")
    print(f"Total: {data.get('total')}")
    if 'unique_list' in data:
        print(f"List length: {len(data['unique_list'])}")
        print(f"First 5: {data['unique_list'][:5]}")

if __name__ == "__main__":
    test_registry_count()
