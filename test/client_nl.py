# New main function for test_client.py
import asyncio
import base64
from fastmcp import Client

client = Client({
    "mcpServers": {
        "servicenow": {
            "command": "servicenow-mcp-server",
            "args": [],
            "transport": "stdio"
        }
    }
})

SERVICENOW_CREDS = {
    "instance_url": "",
    "username": "admin",
    "password": ""
}

async def main():
    async with client:
        await client.ping()
        print("✅ Server is reachable.")

        # --- Test Case 1: Search for an incident ---
        print("\n" + "="*60)
        print("Testing: natural_language_search for an incident...")
        print("="*60)
        
        # First, create an incident to ensure we have something to find
        incident_desc = "Email server is down for Project Phoenix"
        create_payload = {"params": {**SERVICENOW_CREDS, "short_description": incident_desc}}
        await client.call_tool("create_incident", create_payload)
        print(f"  - Created a test incident with description: '{incident_desc}'")

        # Now, search for it using natural language
        nl_query_1 = "show me incidents about Project Phoenix"
        nl_payload_1 = {"params": {**SERVICENOW_CREDS, "query": nl_query_1}}
        
        result_1 = await client.call_tool("natural_language_search", nl_payload_1)
        
        if 'error' in result_1.data:
            print("❌ Test Case 1 Failed:", result_1.data)
        else:
            records = result_1.data.get('result', [])
            print(f"✅ Success! Natural language query found {len(records)} incident(s).")
            if any("Phoenix" in r.get('short_description', '') for r in records):
                print("✅ Verification successful: Found the correct incident.")
            else:
                print("❌ Verification failed: Did not find the test incident.")

        # --- Test Case 2: Search for a change request ---
        print("\n" + "="*60)
        print("Testing: natural_language_search for a change...")
        print("="*60)

        nl_query_2 = "list all changes for network upgrade"
        nl_payload_2 = {"params": {**SERVICENOW_CREDS, "query": nl_query_2}}
        
        result_2 = await client.call_tool("natural_language_search", nl_payload_2)

        if 'error' in result_2.data:
            print("❌ Test Case 2 Failed:", result_2.data)
        else:
            records = result_2.data.get('result', [])
            print(f"✅ Success! Natural language query found {len(records)} change request(s) matching 'network upgrade'.")


if __name__ == "__main__":
    asyncio.run(main())