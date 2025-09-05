from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import pandas as pd
import requests
from difflib import SequenceMatcher
import re
from typing import List, Dict, Optional
import json
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

app = FastAPI(title="NAMASTE-ICD11 Mapping API")

# Configuration
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TOKEN_URL = os.getenv("TOKEN_URL")
SEARCH_URL = os.getenv("SEARCH_URL")

# Pydantic models
class SearchRequest(BaseModel):
    query: str

class ICDCandidate(BaseModel):
    code: str
    title: str
    similarity: float
    source: str

class ConceptMapResponse(BaseModel):
    namaste_code: str
    namaste_term: str
    namaste_definition: str
    extracted_keywords: List[str]
    icd_candidates: List[ICDCandidate]
    best_match: Optional[ICDCandidate]

# NAMASTE data
NAMASTE_DATA = {
    "6": {
        "code": "6",
        "term": "vAtasa~jcayaH",
        "definition": "It is characterized by impaired movements of vāta, fullness of abdomen and aversion to factors causing of increase of vāta such as cold. This may be explained by accumulation of vatadosha at the designated site to a moderate level resulting in accumulation."
    },
    "SR12 (AAA-2)": {
        "code": "SR12 (AAA-2)",
        "term": "vAtavRuddhiH",
        "definition": "It is characterized by roughness or hoarseness of voice, emaciation, blackish discoloration of body, twitching in various parts of body, desire for warmth, insomnia, reduced physical strength, hard stools. This may be explained by marked increase of vatadosha functions and consequent physiological and pathological ramifications."
    }
}

# Token management
_token_cache = None

def get_token():
    global _token_cache
    if _token_cache:
        return _token_cache
    
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "icdapi_access",
        "grant_type": "client_credentials"
    }
    r = requests.post(TOKEN_URL, data=data)
    r.raise_for_status()
    _token_cache = r.json()["access_token"]
    return _token_cache

def search_icd(term, token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Accept-Language": "en",
        "API-Version": "v2"
    }
    params = {"q": term, "flatResults": "true", "chapterFilter": "26"}
    r = requests.get(SEARCH_URL, headers=headers, params=params, verify=False)
    r.raise_for_status()
    return r.json().get("destinationEntities", [])

def extract_keywords(definition):
    stop_words = {'is', 'are', 'the', 'and', 'or', 'of', 'in', 'to', 'by', 'at', 'such', 'as', 'this', 'may', 'be', 'it', 'with', 'a', 'an', 'various', 'parts', 'body', 'functions', 'consequent', 'explained', 'marked', 'increase'}
    
    clean_def = re.sub(r'[^\w\s]', ' ', definition.lower())
    words = clean_def.split()
    keywords = [word for word in words if len(word) > 3 and word not in stop_words]
    
    medical_keywords = []
    for word in keywords:
        if any(term in word for term in ['movement', 'abdomen', 'fullness', 'aversion', 'cold', 'impaired', 'accumulation', 'roughness', 'hoarseness', 'voice', 'emaciation', 'blackish', 'discoloration', 'twitching', 'warmth', 'insomnia', 'strength', 'stools']):
            medical_keywords.append(word)
    
    compound_terms = []
    if 'hoarseness' in definition.lower() and 'voice' in definition.lower():
        compound_terms.append('hoarse voice')
    if 'hard' in definition.lower() and 'stools' in definition.lower():
        compound_terms.append('hard stools')
    if 'physical' in definition.lower() and 'strength' in definition.lower():
        compound_terms.append('weakness')
    
    all_keywords = medical_keywords + compound_terms
    return all_keywords[:8]

def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

@app.get("/", response_class=HTMLResponse)
async def get_frontend():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Medical Concept Mapper - NAMASTE to ICD-11</title>
        <script src="https://d3js.org/d3.v7.min.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Poppins', sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                color: #333;
            }
            
            .container {
                max-width: 1600px;
                margin: 0 auto;
                padding: 20px;
            }
            
            .header {
                text-align: center;
                margin-bottom: 30px;
                color: white;
            }
            
            .header h1 {
                font-size: 3rem;
                font-weight: 800;
                margin-bottom: 15px;
                text-shadow: 0 4px 8px rgba(0,0,0,0.3);
                letter-spacing: -1px;
            }
            
            .header p {
                font-size: 1.3rem;
                opacity: 0.95;
                font-weight: 400;
                text-shadow: 0 2px 4px rgba(0,0,0,0.2);
            }
            
            .search-panel {
                background: rgba(255, 255, 255, 0.98);
                backdrop-filter: blur(20px);
                border-radius: 25px;
                padding: 40px;
                margin-bottom: 30px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.15);
                border: 1px solid rgba(255,255,255,0.3);
            }
            
            .search-container {
                display: flex;
                gap: 20px;
                align-items: center;
                justify-content: center;
                margin-bottom: 30px;
            }
            
            .search-input {
                flex: 1;
                max-width: 500px;
                padding: 18px 25px;
                border: 3px solid #e8eaf6;
                border-radius: 15px;
                font-size: 18px;
                transition: all 0.3s ease;
                background: white;
                font-family: 'Poppins', sans-serif;
                font-weight: 500;
            }
            
            .search-input:focus {
                outline: none;
                border-color: #667eea;
                box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.15);
                transform: translateY(-2px);
            }
            
            .search-btn {
                padding: 18px 35px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 18px;
                font-weight: 700;
                cursor: pointer;
                transition: all 0.3s ease;
                box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
                font-family: 'Poppins', sans-serif;
                letter-spacing: 0.5px;
            }
            
            .search-btn:hover {
                transform: translateY(-3px);
                box-shadow: 0 12px 35px rgba(102, 126, 234, 0.6);
            }
            
            .concept-map-container {
                background: linear-gradient(145deg, #ffffff 0%, #f8f9ff 100%);
                border-radius: 25px;
                box-shadow: 0 25px 80px rgba(0,0,0,0.15);
                border: 2px solid rgba(255,255,255,0.8);
                overflow: hidden;
                min-height: 800px;
                position: relative;
            }
            
            .map-header {
                padding: 30px 40px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                text-align: center;
            }
            
            .map-header h3 {
                font-size: 1.8rem;
                font-weight: 700;
                margin: 0;
                text-shadow: 0 2px 4px rgba(0,0,0,0.2);
                letter-spacing: 0.5px;
            }
            
            .concept-map {
                position: relative;
                background: radial-gradient(circle at center, #f8f9ff 0%, #ffffff 100%);
            }
            
            .node {
                cursor: pointer;
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            }
            
            .node:hover {
                filter: brightness(1.15) saturate(1.2);
                transform: scale(1.1);
            }
            
            .link {
                stroke: url(#linkGradient);
                stroke-opacity: 0.8;
                stroke-width: 3;
                transition: all 0.3s ease;
                filter: drop-shadow(0 2px 4px rgba(0,0,0,0.1));
            }
            
            .namaste-node {
                fill: url(#namasteGradient);
                stroke: #d32f2f;
                stroke-width: 4;
                filter: drop-shadow(0 8px 16px rgba(244, 67, 54, 0.4));
            }
            
            .icd-node {
                fill: url(#icdGradient);
                stroke: #5e7ce0;
                stroke-width: 3;
                filter: drop-shadow(0 6px 12px rgba(94, 124, 224, 0.3));
            }
            
            .best-match-node {
                fill: url(#bestMatchGradient);
                stroke: #2e7d32;
                stroke-width: 5;
                filter: drop-shadow(0 10px 20px rgba(76, 175, 80, 0.5));
                animation: bestMatchPulse 2.5s ease-in-out infinite;
            }
            
            @keyframes bestMatchPulse {
                0%, 100% { 
                    transform: scale(1);
                    filter: drop-shadow(0 10px 20px rgba(76, 175, 80, 0.5));
                }
                50% { 
                    transform: scale(1.08);
                    filter: drop-shadow(0 15px 30px rgba(76, 175, 80, 0.7));
                }
            }
            
            .code-label {
                font-family: 'Poppins', sans-serif;
                font-weight: 700;
                text-anchor: middle;
                pointer-events: none;
                fill: white;
                text-shadow: 0 2px 4px rgba(0,0,0,0.7);
                dominant-baseline: central;
            }
            
            .title-label {
                font-family: 'Poppins', sans-serif;
                font-weight: 600;
                text-anchor: middle;
                pointer-events: none;
                fill: white;
                text-shadow: 0 1px 3px rgba(0,0,0,0.6);
            }
            
            .namaste-term-label {
                font-family: 'Poppins', sans-serif;
                font-weight: 800;
                text-anchor: middle;
                pointer-events: none;
                fill: white;
                text-shadow: 0 3px 6px rgba(0,0,0,0.8);
                dominant-baseline: central;
            }
            
            .tooltip {
                position: absolute;
                background: linear-gradient(145deg, rgba(0, 0, 0, 0.95), rgba(20, 20, 20, 0.95));
                color: white;
                padding: 20px 25px;
                border-radius: 15px;
                font-size: 14px;
                line-height: 1.6;
                pointer-events: none;
                opacity: 0;
                transition: all 0.3s ease;
                max-width: 350px;
                box-shadow: 0 15px 40px rgba(0,0,0,0.4);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(255,255,255,0.1);
                font-family: 'Poppins', sans-serif;
                font-weight: 500;
            }
            
            .loading {
                text-align: center;
                padding: 60px;
                color: #667eea;
                font-weight: 600;
            }
            
            .spinner {
                border: 4px solid #e3f2fd;
                border-top: 4px solid #667eea;
                border-radius: 50%;
                width: 50px;
                height: 50px;
                animation: spin 1.2s linear infinite;
                margin: 0 auto 30px;
            }
            
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            .error-message {
                background: linear-gradient(135deg, #ffebee 0%, #ffcdd2 100%);
                color: #c62828;
                padding: 20px 25px;
                border-radius: 12px;
                margin: 30px;
                border: 2px solid #ef5350;
                font-weight: 600;
                text-align: center;
            }
            
            .crown-icon {
                font-size: 20px;
                margin-right: 8px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🔬 Medical Concept Mapper</h1>
                <p>Intelligent Mapping of NAMASTE Ayurvedic Terms to ICD-11 Classifications</p>
            </div>
            
            <div class="search-panel">
                <div class="search-container">
                    <input type="text" class="search-input" id="searchInput" 
                           placeholder="🔍 Enter NAMASTE code or term (e.g. 'vAtavRuddhiH', 'SR12', '6')">
                    <button class="search-btn" onclick="searchMapping()">
                        <span id="btnText">🚀 Analyze Mapping</span>
                    </button>
                </div>
            </div>
            
            <div class="concept-map-container">
                <div class="map-header">
                    <h3>🎯 Interactive Concept Relationship Network</h3>
                </div>
                <div class="concept-map" id="conceptMap">
                    <div class="loading" style="display: none;" id="loading">
                        <div class="spinner"></div>
                        <p>🧠 Analyzing medical concepts and finding ICD-11 matches...</p>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="tooltip" id="tooltip"></div>

        <script>
            async function searchMapping() {
                const query = document.getElementById('searchInput').value.trim();
                if (!query) {
                    showError('⚠️ Please enter a search term');
                    return;
                }
                
                showLoading(true);
                
                try {
                    const response = await fetch('/search', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ query: query })
                    });
                    
                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(error.detail || 'Search failed');
                    }
                    
                    const data = await response.json();
                    createConceptMap(data);
                } catch (error) {
                    showError('❌ Error: ' + error.message);
                } finally {
                    showLoading(false);
                }
            }
            
            function showLoading(show) {
                const loading = document.getElementById('loading');
                const btnText = document.getElementById('btnText');
                
                loading.style.display = show ? 'block' : 'none';
                btnText.innerHTML = show ? '⏳ Analyzing...' : '🚀 Analyze Mapping';
                
                if (!show) {
                    const existing = document.querySelector('.error-message');
                    if (existing) existing.remove();
                }
            }
            
            function showError(message) {
                const mapContainer = document.getElementById('conceptMap');
                const existing = document.querySelector('.error-message');
                if (existing) existing.remove();
                
                const errorDiv = document.createElement('div');
                errorDiv.className = 'error-message';
                errorDiv.innerHTML = message;
                mapContainer.appendChild(errorDiv);
            }
            
            function createConceptMap(data) {
                const mapContainer = d3.select("#conceptMap");
                mapContainer.selectAll("*").remove();
                
                const width = 1400;
                const height = 800;
                
                const svg = mapContainer
                    .append("svg")
                    .attr("width", width)
                    .attr("height", height);
                
                // Define gradients and patterns
                const defs = svg.append("defs");
                
                // Gradient for NAMASTE node
                const namasteGradient = defs.append("radialGradient")
                    .attr("id", "namasteGradient")
                    .attr("cx", "30%")
                    .attr("cy", "30%");
                namasteGradient.append("stop")
                    .attr("offset", "0%")
                    .attr("stop-color", "#ff6b6b");
                namasteGradient.append("stop")
                    .attr("offset", "100%")
                    .attr("stop-color", "#e53e3e");
                
                // Gradient for ICD nodes
                const icdGradient = defs.append("radialGradient")
                    .attr("id", "icdGradient")
                    .attr("cx", "30%")
                    .attr("cy", "30%");
                icdGradient.append("stop")
                    .attr("offset", "0%")
                    .attr("stop-color", "#74b9ff");
                icdGradient.append("stop")
                    .attr("offset", "100%")
                    .attr("stop-color", "#0984e3");
                
                // Gradient for best match
                const bestMatchGradient = defs.append("radialGradient")
                    .attr("id", "bestMatchGradient")
                    .attr("cx", "30%")
                    .attr("cy", "30%");
                bestMatchGradient.append("stop")
                    .attr("offset", "0%")
                    .attr("stop-color", "#00b894");
                bestMatchGradient.append("stop")
                    .attr("offset", "100%")
                    .attr("stop-color", "#00a085");
                
                // Gradient for links
                const linkGradient = defs.append("linearGradient")
                    .attr("id", "linkGradient")
                    .attr("x1", "0%")
                    .attr("y1", "0%")
                    .attr("x2", "100%")
                    .attr("y2", "100%");
                linkGradient.append("stop")
                    .attr("offset", "0%")
                    .attr("stop-color", "#a29bfe");
                linkGradient.append("stop")
                    .attr("offset", "100%")
                    .attr("stop-color", "#6c5ce7");
                
                // Create nodes and links
                const nodes = [];
                const links = [];
                
                // Central NAMASTE node
                const namasteNode = {
                    id: 'namaste',
                    label: data.namaste_term,
                    code: data.namaste_code,
                    type: 'namaste',
                    fullInfo: `<strong>📋 ${data.namaste_code}</strong><br><strong>🏛️ ${data.namaste_term}</strong><br><br>📝 ${data.namaste_definition}`,
                    displayCode: data.namaste_code
                };
                nodes.push(namasteNode);
                
                // ICD candidate nodes
                const topCandidates = data.icd_candidates.slice(0, 8);
                topCandidates.forEach((candidate, i) => {
                    const isBest = data.best_match && candidate.code === data.best_match.code;
                    const candidateNode = {
                        id: `icd_${i}`,
                        label: candidate.title.length > 25 ? candidate.title.substring(0, 25) + '...' : candidate.title,
                        code: candidate.code,
                        fullLabel: candidate.title,
                        type: isBest ? 'best' : 'icd',
                        fullInfo: `${isBest ? '<span class="crown-icon">👑</span>' : '🔗'} <strong>ICD-11:</strong> ${candidate.code}<br><br><strong>📊 Title:</strong> ${candidate.title}<br><br><strong>📈 Similarity:</strong> ${(candidate.similarity * 100).toFixed(1)}%<br><br><strong>🔍 Source:</strong> ${candidate.source}${isBest ? '<br><br><strong>🏆 BEST MATCH</strong>' : ''}`,
                        similarity: candidate.similarity,
                        isBest: isBest,
                        displayCode: candidate.code
                    };
                    nodes.push(candidateNode);
                    links.push({ 
                        source: 'namaste', 
                        target: `icd_${i}`, 
                        strength: isBest ? 1.0 : 0.6 + (candidate.similarity * 0.4)
                    });
                });
                
                // Create force simulation
                const simulation = d3.forceSimulation(nodes)
                    .force("link", d3.forceLink(links).id(d => d.id).distance(d => 180 + (d.strength * 60)))
                    .force("charge", d3.forceManyBody().strength(-800))
                    .force("center", d3.forceCenter(width / 2, height / 2))
                    .force("collision", d3.forceCollide().radius(80));
                
                // Create links
                const link = svg.append("g")
                    .selectAll("line")
                    .data(links)
                    .enter().append("line")
                    .attr("class", "link")
                    .style("stroke-width", d => 3 + (d.strength * 4))
                    .style("stroke-opacity", d => 0.6 + (d.strength * 0.3));
                
                // Create nodes
                const node = svg.append("g")
                    .selectAll("circle")
                    .data(nodes)
                    .enter().append("circle")
                    .attr("class", d => `node ${d.type}-node`)
                    .attr("r", d => {
                        if (d.type === 'namaste') return 70;
                        if (d.type === 'best') return 60;
                        return 45;
                    })
                    .call(d3.drag()
                        .on("start", dragstarted)
                        .on("drag", dragged)
                        .on("end", dragended));
                
                // Add code labels
                const codeText = svg.append("g")
                    .selectAll("text")
                    .data(nodes)
                    .enter().append("text")
                    .attr("class", "code-label")
                    .text(d => d.displayCode)
                    .style("font-size", d => {
                        if (d.type === 'namaste') return '16px';
                        if (d.type === 'best') return '14px';
                        return '12px';
                    });
                
                // Add title labels for ICD nodes
                const titleText = svg.append("g")
                    .selectAll("text")
                    .data(nodes.filter(d => d.type !== 'namaste'))
                    .enter().append("text")
                    .attr("class", "title-label")
                    .style("font-size", d => {
                        if (d.type === 'best') return '11px';
                        return '9px';
                    })
                    .each(function(d) {
                        const textElement = d3.select(this);
                        const words = d.label.split(' ');
                        const maxCharsPerLine = d.type === 'best' ? 12 : 10;
                        
                        let line = [];
                        let lineNumber = 0;
                        
                        for (let i = 0; i < words.length && lineNumber < 3; i++) {
                            const testLine = line.concat(words[i]).join(' ');
                            if (testLine.length > maxCharsPerLine && line.length > 0) {
                                textElement.append("tspan")
                                    .attr("x", 0)
                                    .attr("dy", lineNumber === 0 ? "1.2em" : "1.1em")
                                    .text(line.join(' '));
                                line = [words[i]];
                                lineNumber++;
                            } else {
                                line.push(words[i]);
                            }
                        }
                        
                        if (line.length > 0 && lineNumber < 3) {
                            textElement.append("tspan")
                                .attr("x", 0)
                                .attr("dy", lineNumber === 0 ? "1.2em" : "1.1em")
                                .text(line.join(' '));
                        }
                    });
                
                // NAMASTE term label
                const namasteText = svg.append("g")
                    .selectAll("text")
                    .data(nodes.filter(d => d.type === 'namaste'))
                    .enter().append("text")
                    .attr("class", "namaste-term-label")
                    .text(d => d.label)
                    .style("font-size", "18px");
                
                // Tooltip
                const tooltip = d3.select("#tooltip");
                
                node
                    .on("mouseover", function(event, d) {
                        tooltip.transition().duration(200).style("opacity", 1);
                        tooltip.html(d.fullInfo)
                            .style("left", (event.pageX + 20) + "px")
                            .style("top", (event.pageY - 10) + "px");
                        
                        // Highlight effects
                        d3.select(this).style("filter", "brightness(1.3) saturate(1.5)");
                        link.style("stroke-opacity", l => 
                            (l.source.id === d.id || l.target.id === d.id) ? 1 : 0.2
                        );
                    })
                    .on("mouseout", function(d) {
                        tooltip.transition().duration(300).style("opacity", 0);
                        d3.select(this).style("filter", null);
                        link.style("stroke-opacity", d => 0.6 + (d.strength * 0.3));
                    });
                
                // Update positions
                simulation.on("tick", () => {
                    link
                        .attr("x1", d => d.source.x)
                        .attr("y1", d => d.source.y)
                        .attr("x2", d => d.target.x)
                        .attr("y2", d => d.target.y);
                    
                    node
                        .attr("cx", d => Math.max(80, Math.min(width - 80, d.x)))
                        .attr("cy", d => Math.max(80, Math.min(height - 80, d.y)));
                    
                    codeText
                        .attr("x", d => Math.max(80, Math.min(width - 80, d.x)))
                        .attr("y", d => {
                            const y = Math.max(80, Math.min(height - 80, d.y));
                            return d.type === 'namaste' ? y - 20 : y - 15;
                        });
                    
                    titleText
                        .attr("x", d => Math.max(80, Math.min(width - 80, d.x)))
                        .attr("y", d => {
                            const y = Math.max(80, Math.min(height - 80, d.y));
                            return y + 10;
                        });
                    
                    namasteText
                        .attr("x", d => Math.max(80, Math.min(width - 80, d.x)))
                        .attr("y", d => Math.max(80, Math.min(height - 80, d.y)));
                });
                
                function dragstarted(event, d) {
                    if (!event.active) simulation.alphaTarget(0.3).restart();
                    d.fx = d.x;
                    d.fy = d.y;
                }
                
                function dragged(event, d) {
                    d.fx = event.x;
                    d.fy = event.y;
                }
                
                function dragended(event, d) {
                    if (!event.active) simulation.alphaTarget(0);
                    d.fx = null;
                    d.fy = null;
                }
            }
            
            document.getElementById('searchInput').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    searchMapping();
                }
            });
        </script>
    </body>
    </html>
    """

@app.post("/search", response_model=ConceptMapResponse)
async def search_namaste_mapping(request: SearchRequest):
    query = request.query.strip()
    
    # Find NAMASTE entry
    namaste_entry = None
    for code, entry in NAMASTE_DATA.items():
        if (query.lower() in code.lower() or 
            query.lower() in entry["term"].lower() or
            query == code):
            namaste_entry = entry
            break
    
    if not namaste_entry:
        raise HTTPException(status_code=404, detail=f"NAMASTE entry not found for query: '{query}'. Available entries: {list(NAMASTE_DATA.keys())}")
    
    try:
        token = get_token()
        
        # Extract keywords
        keywords = extract_keywords(namaste_entry["definition"])
        
        # Search ICD-11
        all_candidates = {}
        
        # Search with NAMASTE term
        candidates = search_icd(namaste_entry["term"], token)
        for c in candidates:
            title = c.get("title", "")
            code = c.get("theCode", "")
            if title and code:
                score = similarity(namaste_entry["term"], title)
                all_candidates[code] = (title, score, "NAMASTE_term")
        
        # Search with keywords
        for keyword in keywords:
            candidates = search_icd(keyword, token)
            for c in candidates:
                title = c.get("title", "")
                code = c.get("theCode", "")
                if title and code:
                    score_vs_term = similarity(namaste_entry["term"], title)
                    score_vs_keyword = similarity(keyword, title)
                    score = max(score_vs_term, score_vs_keyword * 0.8)
                    
                    if code not in all_candidates or score > all_candidates[code][1]:
                        all_candidates[code] = (title, score, f"keyword: {keyword}")
        
        # Convert to response format
        icd_candidates = []
        best_match = None
        best_score = 0.0
        
        for code, (title, score, source) in all_candidates.items():
            candidate = ICDCandidate(
                code=code,
                title=title,
                similarity=round(score, 3),
                source=source
            )
            icd_candidates.append(candidate)
            
            if score > best_score:
                best_score = score
                best_match = candidate
        
        # Sort by similarity
        icd_candidates.sort(key=lambda x: x.similarity, reverse=True)
        
        return ConceptMapResponse(
            namaste_code=namaste_entry["code"],
            namaste_term=namaste_entry["term"],
            namaste_definition=namaste_entry["definition"],
            extracted_keywords=keywords,
            icd_candidates=icd_candidates,
            best_match=best_match
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)