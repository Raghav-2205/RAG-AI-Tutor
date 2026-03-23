from _bootstrap import ensure_project_root

ensure_project_root()

from backend.core.llm_interface import llm_client

def test_llm():
    print("Testing LLM Client...")
    try:
        response = llm_client.generate("Hello, are you working?", temperature=0.0)
        print(f"Response: {response}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_llm()
