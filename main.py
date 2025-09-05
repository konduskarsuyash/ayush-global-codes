import pandas as pd
import requests
from difflib import SequenceMatcher
import re

import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# --------------------
# Step 1. Authenticate
# --------------------
def get_token():
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "icdapi_access",
        "grant_type": "client_credentials"
    }
    r = requests.post(TOKEN_URL, data=data)
    r.raise_for_status()
    print("Token retrieved successfully and token is ", r.json()["access_token"])
    return r.json()["access_token"]

# --------------------
# Step 2. ICD-11 Search
# --------------------
def search_icd(term, token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Accept-Language": "en",
        "API-Version": "v2"
    }
    params = {"q": term, "flatResults": "true",    "chapterFilter": "26"  # restricts results to TM2
}
    r = requests.get(SEARCH_URL, headers=headers, params=params, verify=False)
    r.raise_for_status()
    return r.json().get("destinationEntities", [])

# --------------------
# Step 3. Extract Keywords from Definition
# --------------------
def extract_keywords(definition):
    """Extract meaningful keywords from long definition for better ICD search"""
    # Remove common words and focus on medical terms
    stop_words = {'is', 'are', 'the', 'and', 'or', 'of', 'in', 'to', 'by', 'at', 'such', 'as', 'this', 'may', 'be', 'it', 'with', 'a', 'an', 'various', 'parts', 'body', 'functions', 'consequent', 'explained', 'marked', 'increase'}
    
    # Clean and tokenize
    clean_def = re.sub(r'[^\w\s]', ' ', definition.lower())
    words = clean_def.split()
    
    # Filter meaningful keywords
    keywords = [word for word in words if len(word) > 3 and word not in stop_words]
    
    # Focus on medical-relevant terms for vAtavRuddhiH
    medical_keywords = []
    for word in keywords:
        if any(term in word for term in ['roughness', 'hoarseness', 'voice', 'emaciation', 'blackish', 'discoloration', 'twitching', 'warmth', 'insomnia', 'strength', 'stools', 'physiological', 'pathological']):
            medical_keywords.append(word)
    
    # Also add compound terms that might be relevant
    compound_terms = []
    if 'hoarseness' in definition.lower() and 'voice' in definition.lower():
        compound_terms.append('hoarse voice')
    if 'hard' in definition.lower() and 'stools' in definition.lower():
        compound_terms.append('hard stools')
    if 'physical' in definition.lower() and 'strength' in definition.lower():
        compound_terms.append('weakness')
    if 'blackish' in definition.lower() and 'discoloration' in definition.lower():
        compound_terms.append('skin discoloration')
    
    # Combine single words and compound terms
    all_keywords = medical_keywords + compound_terms
    
    return all_keywords[:8]  # Return top 8 keywords

# --------------------
# Step 4. Similarity
# --------------------
def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# --------------------
# Step 5. Build Mapping for Specific Entry
# --------------------
def build_mapping_specific():
    # Specific entry data
    nam_code = "SR12 (AAA-2)"
    nam_term = "vAtavRuddhiH"
    nam_def = "It is characterized by roughness or hoarseness of voice, emaciation, blackish discoloration of body, twitching in various parts of body, desire for warmth, insomnia, reduced physical strength, hard stools. This may be explained by marked increase of vatadosha functions and consequent physiological and pathological ramifications."
    
    token = get_token()
    print(f"\nProcessing NAMASTE entry: {nam_term}")
    
    results = []
    best_overall_match = None
    best_overall_score = 0.0
    all_candidates = {}  # Store all unique candidates
    
    # Priority 1: Try NAMASTE term
    print(f"\n1. Searching with NAMASTE term: '{nam_term}'")
    candidates = search_icd(nam_term, token)
    print(f"   Found {len(candidates)} candidates")
    
    if candidates:
        for c in candidates:
            title = c.get("title", "")
            code = c.get("theCode", "")
            score = similarity(nam_term, title)
            all_candidates[code] = (title, score, "NAMASTE_term")
            print(f"   - {code}: {title} (similarity: {score:.3f})")
            
            if score > best_overall_score:
                best_overall_score = score
                best_overall_match = (code, title, "NAMASTE_term")

    # Priority 2: Try with extracted keywords from definition
    if nam_def.strip():
        keywords = extract_keywords(nam_def)
        print(f"\n2. Extracted keywords from definition: {keywords}")
        
        for keyword in keywords:
            print(f"\n   Searching with keyword: '{keyword}'")
            candidates = search_icd(keyword, token)
            print(f"   Found {len(candidates)} candidates")
            
            for c in candidates:
                title = c.get("title", "")
                code = c.get("theCode", "")
                # Calculate similarity against the symptoms, not just the term
                score_vs_term = similarity(nam_term, title)
                score_vs_keyword = similarity(keyword, title)
                # Use higher score for better matching
                score = max(score_vs_term, score_vs_keyword * 0.8)
                
                if code not in all_candidates or score > all_candidates[code][1]:
                    all_candidates[code] = (title, score, f"keyword: {keyword}")
                
                print(f"   - {code}: {title} (similarity: {score:.3f})")
                
                if score > best_overall_score:
                    best_overall_score = score
                    best_overall_match = (code, title, f"keyword: {keyword}")

    # Priority 3: Try with symptom combinations
    symptom_phrases = [
        "voice hoarseness",
        "muscle twitching", 
        "sleep disorders",
        "constipation",
        "skin discoloration",
        "muscle weakness"
    ]
    
    print(f"\n3. Searching with symptom combinations...")
    for phrase in symptom_phrases:
        print(f"\n   Searching with phrase: '{phrase}'")
        candidates = search_icd(phrase, token)
        print(f"   Found {len(candidates)} candidates")
        
        for c in candidates:
            title = c.get("title", "")
            code = c.get("theCode", "")
            score = similarity(phrase, title) * 0.9  # Slightly lower weight for phrase matching
            
            if code not in all_candidates or score > all_candidates[code][1]:
                all_candidates[code] = (title, score, f"symptom: {phrase}")
            
            print(f"   - {code}: {title} (similarity: {score:.3f})")
            
            if score > best_overall_score:
                best_overall_score = score
                best_overall_match = (code, title, f"symptom: {phrase}")

    # Results
    result = {
        "NAMASTE_CODE": nam_code,
        "NAMASTE_TERM": nam_term,
        "ICD11_CODE": best_overall_match[0] if best_overall_match else None,
        "ICD11_TERM": best_overall_match[1] if best_overall_match else None,
        "SIMILARITY": round(best_overall_score, 3),
        "MATCH_SOURCE": best_overall_match[2] if best_overall_match else None
    }
    
    print(f"\n=== FINAL RESULT ===")
    print(f"NAMASTE: {nam_code} - {nam_term}")
    print(f"ICD-11: {result['ICD11_CODE']} - {result['ICD11_TERM']}")
    print(f"Similarity: {result['SIMILARITY']}")
    print(f"Matched via: {result['MATCH_SOURCE']}")
    
    # Show top 5 candidates for review
    print(f"\n=== TOP CANDIDATES ===")
    sorted_candidates = sorted(all_candidates.items(), key=lambda x: x[1][1], reverse=True)
    for i, (code, (title, score, source)) in enumerate(sorted_candidates[:5]):
        print(f"{i+1}. {code}: {title} (score: {score:.3f}, via: {source})")
    
    # Save to CSV
    out_df = pd.DataFrame([result])
    output_file = "vAtavRuddhiH_specific_mapping.csv"
    out_df.to_csv(output_file, index=False)
    print(f"\nMapping saved to {output_file}")

# --------------------
# Run
# --------------------
if __name__ == "__main__":
    CLIENT_ID = os.getenv("CLIENT_ID")
    CLIENT_SECRET = os.getenv("CLIENT_SECRET")
    TOKEN_URL = os.getenv("TOKEN_URL")
    SEARCH_URL = os.getenv("SEARCH_URL")

    build_mapping_specific()
