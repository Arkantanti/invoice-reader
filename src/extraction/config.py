import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in .env")

OPENAI_MODEL = "gpt-5.4"

# The buyer — i.e. us. Naming our own company in the extraction prompt helps the
# model tell the vendor/seller's details apart from the recipient's.
COMPANY_NAME = os.getenv("COMPANY_NAME")