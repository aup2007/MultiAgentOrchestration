"""
F1 Agent Advanced Telemetry Stress Test
========================================

This script sends 5 highly specific F1 queries to your backend to stress-test
the agent's ability to handle deep telemetry analysis, cache hits vs. API downloads,
and edge cases.

Each query covers a distinct telemetry analysis domain:
1. Tire Management & Stints
2. Sector-Specific Telemetry
3. Pit Stop Strategy Analysis
4. Teammate Pace Comparison
5. Edge Case / Outlier Handling

Usage:
    python test_f1_agent.py

Requirements:
    - Backend running at http://localhost:8000/chat
    - requests library: pip install requests
"""

import requests
import time
import json
from typing import Tuple, Dict, Any
from datetime import datetime

# Configuration
BACKEND_URL = "http://localhost:8000/chat"
REQUEST_TIMEOUT = 120  # seconds (API downloads can take time)

# Advanced F1 telemetry queries targeting specific analysis domains
ADVANCED_QUERIES = [
    {
        "name": "Tire Management & Stints",
        "description": "Analyze specific driver's stint length on a tire compound",
        "query": "How many laps did Lewis Hamilton manage on the Hard compound during his second stint at Silverstone 2023, and what was his average lap time drop-off compared to his first stint on the Medium compound? Include sector-by-sector comparison."
    },
    {
        "name": "Sector-Specific Telemetry",
        "description": "Isolate performance in a specific sector during a critical race phase",
        "query": "Compare the average Sector 2 times between Max Verstappen and Charles Leclerc during the final 10 laps of the 2024 Japanese Grand Prix. Who was faster and by how much? Include their tire compound at that stage."
    },
    {
        "name": "Pit Stop Strategy Analysis",
        "description": "Deduce team strategy from pit timing and tire changes",
        "query": "Analyze the pit stop strategy for Ferrari during the 2024 Monaco Grand Prix. For both Leclerc and Sainz: what were the exact lap numbers of their pit stops, tire compounds used in each stint, and how did pit loss (time spent in pits) compare between the two drivers?"
    },
    {
        "name": "Teammate Pace Comparison",
        "description": "Compare teammates in the same car during specific race phase",
        "query": "During the 2023 Hungarian Grand Prix, compare the pace of George Russell versus Lewis Hamilton at Mercedes on Medium compound tires. Focus on the middle stint (laps 20-40) and quantify any performance gaps. Include their pit stop timings."
    },
    {
        "name": "Edge Case / Outlier",
        "description": "Handle DNF, safety car, or lap time anomalies",
        "query": "In the 2024 British Grand Prix, Lando Norris had a significant pit stop delay that cost him approximately 5 seconds. How did this impact his subsequent lap times (within 5 laps after the stop) compared to his pre-stop pace? Were there any anomalies in his telemetry data?"
    }
]


def send_query(query_text: str, timeout: int = REQUEST_TIMEOUT) -> Tuple[float, Dict[str, Any]]:
    """
    Send a query to the backend and measure response time.

    Args:
        query_text: The F1 query to send
        timeout: Request timeout in seconds

    Returns:
        Tuple of (response_time_seconds, response_dict)
        response_dict may contain:
        - "final_response": The main text response
        - "response": Alternative response field
        - "error": Error message if request failed
        - "raw_response": Full raw response if parsing needed
    """
    payload = {"query": query_text}

    start_time = time.time()
    try:
        response = requests.post(
            BACKEND_URL,
            json=payload,
            timeout=timeout
        )
        elapsed_time = time.time() - start_time

        # Try to parse JSON
        try:
            response_json = response.json()
        except json.JSONDecodeError:
            response_json = {"raw_response": response.text}

        # Check HTTP status
        if response.status_code != 200:
            response_json["http_error"] = f"{response.status_code}: {response.reason}"

        return elapsed_time, response_json

    except requests.exceptions.Timeout:
        elapsed_time = time.time() - start_time
        return elapsed_time, {
            "error": f"Request timed out after {timeout}s",
            "error_type": "TIMEOUT"
        }
    except requests.exceptions.ConnectionError as e:
        elapsed_time = time.time() - start_time
        return elapsed_time, {
            "error": f"Failed to connect to {BACKEND_URL}: {str(e)}",
            "error_type": "CONNECTION"
        }
    except Exception as e:
        elapsed_time = time.time() - start_time
        return elapsed_time, {
            "error": f"Unexpected error: {str(e)}",
            "error_type": "UNKNOWN"
        }


def extract_response_text(response: Dict[str, Any]) -> str:
    """
    Extract the main response text from various possible response formats.

    Args:
        response: The response dictionary from the backend

    Returns:
        String response text or error message
    """
    if "error" in response:
        return f"❌ Error ({response.get('error_type', 'UNKNOWN')}): {response['error']}"

    if "http_error" in response:
        return f"❌ HTTP Error: {response['http_error']}"

    # Try common response field names
    for field in ["final_response", "response", "result", "answer"]:
        if field in response and response[field]:
            return response[field]

    # Fallback: return raw response
    if "raw_response" in response:
        return response["raw_response"]

    return "⚠️ No response text found in response"


def print_divider(char: str = "=", width: int = 100):
    """Print a divider line."""
    print(char * width)


def print_result(
    index: int,
    name: str,
    description: str,
    query: str,
    elapsed_time: float,
    response: Dict[str, Any]
):
    """Pretty print the test result with all relevant information."""
    print_divider()
    print(f"TEST {index}/5: {name}")
    print_divider()

    print(f"📝 Description: {description}\n")

    print("📋 Query:")
    print(f"  {query}\n")

    print(f"⏱️  Response Time: {elapsed_time:.2f} seconds", end="")
    if elapsed_time < 3:
        print(" ⚡ (Likely Cache Hit)")
    elif elapsed_time < 10:
        print(" 🔄 (Mixed/Partial Cache)")
    else:
        print(" 🌐 (Likely API Download)")

    response_text = extract_response_text(response)
    print(f"\n✅ Response:\n")

    # Format the response nicely
    if "error" in response or "http_error" in response:
        print(f"  {response_text}\n")
    else:
        # Wrap long text
        lines = response_text.split("\n")
        for line in lines:
            if len(line) > 95:
                # Simple word wrap for long lines
                import textwrap
                wrapped = textwrap.wrap(line, width=95)
                for wrapped_line in wrapped:
                    print(f"  {wrapped_line}")
            else:
                print(f"  {line}")
        print()


def print_header():
    """Print the test header."""
    print_divider("=", 100)
    print("🏎️  F1 AGENT ADVANCED TELEMETRY STRESS TEST")
    print_divider("=", 100)
    print(f"\n🎯 Backend URL: {BACKEND_URL}")
    print(f"📊 Test Count: {len(ADVANCED_QUERIES)}")
    print(f"⏱️  Timeout per request: {REQUEST_TIMEOUT}s")
    print(f"🕐 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


def print_summary(results: list):
    """Print summary statistics."""
    print_divider("=", 100)
    print("📊 TEST SUMMARY & BENCHMARKS")
    print_divider("=", 100)

    successful = sum(1 for r in results if "error" not in r["response"] and "http_error" not in r["response"])
    failed = len(results) - successful
    times = [r["elapsed_time"] for r in results]
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    total_time = sum(times)

    print(f"\n✅ Successful Queries: {successful}/{len(results)}")
    print(f"❌ Failed Queries: {failed}/{len(results)}")

    print(f"\n⏱️  Response Time Statistics:")
    print(f"   • Total Time: {total_time:.2f}s")
    print(f"   • Average: {avg_time:.2f}s")
    print(f"   • Minimum: {min_time:.2f}s ⚡ (Cache Hit)")
    print(f"   • Maximum: {max_time:.2f}s 🌐 (API Download)")
    print(f"   • Range: {max_time - min_time:.2f}s")

    print(f"\n📋 Response Times by Query:")
    for result in results:
        is_error = "error" in result["response"] or "http_error" in result["response"]
        status = "❌" if is_error else "✅"
        elapsed = result["elapsed_time"]

        # Determine cache status
        if elapsed < 3:
            cache_status = "⚡ CACHE"
        elif elapsed < 10:
            cache_status = "🔄 MIXED"
        else:
            cache_status = "🌐 API"

        print(f"   {status} {result['name']:<35} {elapsed:>7.2f}s  {cache_status}")

    print(f"\n🔍 Cache Hit Detection:")
    cache_hits = sum(1 for r in results if r["elapsed_time"] < 3)
    print(f"   • Estimated Cache Hits: {cache_hits}/{len(results)}")
    print(f"   • Cache Hit Rate: {(cache_hits/len(results)*100):.0f}%")

    print(f"\n💡 Insights:")
    if cache_hits == 0:
        print(f"   • All queries triggered API downloads (no cached data)")
        print(f"   • Next run should be faster if queries are repeated")
    elif cache_hits == len(results):
        print(f"   • All queries hit cache (data was pre-cached)")
        print(f"   • Excellent performance!")
    else:
        print(f"   • Mixed cache/API patterns indicate selective data refresh")
        first_slow = next((r for r in results if r["elapsed_time"] >= 10), None)
        if first_slow:
            print(f"   • First slow query: '{first_slow['name']}' ({first_slow['elapsed_time']:.2f}s)")
            print(f"   • Subsequent queries may benefit from this sync")

    print_divider("=", 100)
    print(f"✅ Test completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


def main():
    """Run all advanced F1 telemetry stress tests."""
    print_header()

    results = []

    for idx, test_case in enumerate(ADVANCED_QUERIES, 1):
        name = test_case["name"]
        description = test_case["description"]
        query = test_case["query"]

        print(f"[{idx}/{len(ADVANCED_QUERIES)}] Sending query: {name}...")
        print("Please wait...\n")

        elapsed_time, response = send_query(query)
        results.append({
            "index": idx,
            "name": name,
            "description": description,
            "query": query,
            "elapsed_time": elapsed_time,
            "response": response
        })

        print_result(idx, name, description, query, elapsed_time, response)

    # Print summary
    print_summary(results)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
