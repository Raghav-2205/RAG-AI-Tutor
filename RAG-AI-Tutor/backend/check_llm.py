from backend.core.llm_interface import llm_client

def test_llm():
    print(f"Testing LLM with model: {llm_client.model_name}")
    print(f"API URL: {llm_client.api_url}")
    
    try:
        response = llm_client.generate("Hello, are you working?", temperature=0.7)
        print("\n⬇️ LLM Response ⬇️")
        print(response)
        
        if "LLM Request Failed" in response or "Error" in response:
            print("\n❌ Test Failed")
        else:
            print("\n✅ Test Passed")
            
    except Exception as e:
        print(f"\n❌ Exception: {e}")

if __name__ == "__main__":
    test_llm()
