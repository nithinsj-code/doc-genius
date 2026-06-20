import google.generativeai as genai
import os
import json
from dotenv import load_dotenv

load_dotenv("backend/.env")
genai.configure(api_key=os.getenv("GEMINI_API"))

texts = ["hello world", "second text"]
try:
    resp = genai.embed_content(
        model="models/gemini-embedding-2",
        content=texts
    )
    print("KEYS:", resp.keys())
    print("EMBEDDING TYPE:", type(resp['embedding']))
    print("LENGTH:", len(resp['embedding']))
    print("DIMENSIONS:", len(resp['embedding'][0]))
except Exception as e:
    print("ERROR:", e)
