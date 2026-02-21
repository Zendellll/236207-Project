import os
import json
import time
import pandas as pd
from tavily import TavilyClient

# ==========================================
# CONFIGURATION
# ==========================================
TAVILY_API_KEY = "MY_KEY"
INPUT_CSV = "queries.csv"
OUTPUT_FILE = "harvested_sources_interactive.json"
QUERIES_PER_DOMAIN = 10 

# The Search Footprint: Forces the search engine to only return interactive pages
INTERACTIVE_FOOTPRINT = ' AND ("leave a reply" OR "post a comment" OR "leave a comment" OR intitle:forum OR inurl:community)'

tavily = TavilyClient(api_key=TAVILY_API_KEY)

def main():
    # ---------------------------------------------------------
    # 1. Load the Target List
    # ---------------------------------------------------------
    if not os.path.exists(INPUT_CSV):
        print(f"❌ Error: {INPUT_CSV} not found. Please ensure the file is in the same directory.")
        return

    df = pd.read_csv(INPUT_CSV)
    
    # Filter: Keep only top 10 per domain
    df_targets = df.groupby('Domain').head(QUERIES_PER_DOMAIN).reset_index(drop=True)
    
    print(f"🚀 Found {len(df_targets)} queries to run. Starting Harvester...\n")

    harvested_data = []

    # ---------------------------------------------------------
    # 2. Run Tavily with the Interactive Footprint
    # ---------------------------------------------------------
    for _, row in df_targets.iterrows():
        domain = row['Domain']
        query_id = row['Query ID']
        base_query = row['Query']
        
        # Inject the footprint into the query
        augmented_query = base_query + INTERACTIVE_FOOTPRINT
        
        print(f"🔍 Searching: [{domain}] ID:{query_id}...")
        
        try:
            # Fetch sources
            response = tavily.search(
                query=augmented_query,
                search_depth="advanced", 
                max_results=5
            )
            
            sources_data = [
                {"url": result['url'], "title": result['title']} 
                for result in response['results']
            ]
            
            result_obj = {
                "Domain": domain,
                "Query ID": query_id,
                "Query": base_query, # Save the original query
                "Sources": sources_data
            }
            
            # Append and save incrementally
            harvested_data.append(result_obj)
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(harvested_data, f, indent=4, ensure_ascii=False)

            time.sleep(1.5) # Prevent rate limits

        except Exception as e:
            print(f"❌ Failed on {query_id}: {e}")
            if "429" in str(e) or "blocked" in str(e).lower():
                print("⏳ Rate limit hit. Sleeping for 10 seconds...")
                time.sleep(10)

    print(f"\n✅ Harvesting Complete. Data saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()