from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import UploadFile, File

import pdfplumber
from docx import Document
import io

import os
from pydantic import BaseModel
from transformers import pipeline
from typing import List
import torch

# ================== APP SETUP ==================

app = FastAPI(
    title="SummarizePro Backend",
    description="Text Summarization API using BART",
    version="1.0.0"
)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# Allow frontend (PWA / WebView) to access API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================== MODEL LOADING ==================
print("Loading summarization model...")

device = 0 if torch.cuda.is_available() else -1

summarizer = pipeline(
    "summarization",
    model="facebook/bart-large-cnn",
    framework="pt",   # 👈 IMPORTANT
    device=device
)


print("Model loaded successfully ✅")

# ================== REQUEST SCHEMA ==================

class SummarizeRequest(BaseModel):
    text: str
    max_length: int = 60
    min_length: int = 20

class SummarizeResponse(BaseModel):
    summary: str

# ================== HELPERS ==================

MAX_CHARS = 4000  # Safe chunk size for BART

def chunk_text(text: str) -> List[str]:
    """
    Split long text into manageable chunks
    """
    chunks = []
    current = ""

    for paragraph in text.split("\n"):
        if len(current) + len(paragraph) <= MAX_CHARS:
            current += " " + paragraph
        else:
            chunks.append(current.strip())
            current = paragraph

    if current.strip():
        chunks.append(current.strip())

    return chunks
def extract_text_from_pdf(file_bytes: bytes) -> str:
    text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text


def extract_text_from_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)

# ================== API ENDPOINT ==================

@app.post("/summarize", response_model=SummarizeResponse)
def summarize_text(data: SummarizeRequest):
    if not data.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    chunks = chunk_text(data.text)

    summaries = []
    for chunk in chunks:
        result = summarizer(
            chunk,
            max_length=data.max_length,
            min_length=data.min_length,
            do_sample=False
        )
        summaries.append(result[0]["summary_text"])

    final_summary = " ".join(summaries)

    return {"summary": final_summary}

# ================== HEALTH CHECK ==================
@app.post("/summarize-file")
async def summarize_file(file: UploadFile = File(...)):
    print("✅ HIT /summarize-file")
    print("Filename:", file.filename)
    print("Content-Type:", file.content_type)


    # ✅ Read file bytes
    file_bytes = await file.read()
    filename = file.filename.lower()

    # ✅ Detect file type & extract text
    if filename.endswith(".pdf"):
        text = extract_text_from_pdf(file_bytes)

    elif filename.endswith(".docx"):
        text = extract_text_from_docx(file_bytes)

    elif filename.endswith(".txt"):
        text = file_bytes.decode("utf-8", errors="ignore")

    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type (PDF, DOCX, TXT only)"
        )

    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="File contains no readable text"
        )

    # ✅ SAME pipeline as text summarization
    chunks = chunk_text(text)
    summaries = []

    for chunk in chunks:
        result = summarizer(
            chunk,
            max_length=60,
            min_length=20,
            do_sample=False
        )
        summaries.append(result[0]["summary_text"])

    final_summary = " ".join(summaries)

    return {"summary": final_summary}

@app.get("/")
def serve_frontend():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

