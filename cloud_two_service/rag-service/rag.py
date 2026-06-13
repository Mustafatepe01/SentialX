import json
import re
from typing import List, Tuple, Dict, Any
import litellm
from config import config
from models import Regulation, Source, SolutionCriteria


def load_tree(index_path: str) -> Tuple[List, Dict]:
    with open(index_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    tree = data["structure"]
    node_map = {}
    _build_node_map(tree, node_map)
    return tree, node_map


def _build_node_map(nodes: List, mapping: Dict):
    for node in nodes:
        mapping[node["node_id"]] = node
        if "nodes" in node:
            _build_node_map(node["nodes"], mapping)


def remove_text(nodes: List) -> List:
    result = []
    for node in nodes:
        n = {k: v for k, v in node.items() if k != "text"}
        if "nodes" in node:
            n["nodes"] = remove_text(node["nodes"])
        result.append(n)
    return result


def extract_sources(text: str) -> List[Source]:
    sources = []
    # Linkli kaynak: [kaynak adı](url)
    md_links = re.findall(r'Kaynak:\s*\[([^\]]+)\]\((https?://[^\)]+)\)', text)
    for name, url in md_links:
        sources.append(Source(name=name, url=url))
    # Linksiz kaynak
    plain = re.findall(r'Kaynak:\s*([^\[\n]+?)(?:\n|$)', text)
    for p in plain:
        p = p.strip()
        if p and not p.startswith('['):
            sources.append(Source(name=p, url=None))
    return sources


def extract_regulations(text: str) -> List[Regulation]:
    regs = []
    # Linkli mevzuat
    md_links = re.findall(
        r'\[([^\]]+(?:Yönetmeliği|Kanunu|Tüzük|Yönetmelik|Tebliğ)[^\]]*)\]\((https?://[^\)]+)\)',
        text
    )
    for name, url in md_links:
        regs.append(Regulation(name=name.strip(), url=url))
    return regs


def extract_solution_criteria(text: str) -> SolutionCriteria:
    mandatory = []
    recommended = []

    # Zorunlu bölümü
    zorunlu_match = re.search(r'\*\*Zorunlu:\*\*(.+?)(?:\*\*Önerilen|\Z)', text, re.DOTALL)
    if not zorunlu_match:
        zorunlu_match = re.search(r'Zorunlu:(.+?)(?:Önerilen:|\Z)', text, re.DOTALL)
    if zorunlu_match:
        lines = zorunlu_match.group(1).strip().split('\n')
        for line in lines:
            line = line.strip().lstrip('- •').strip()
            if line and len(line) > 10:
                mandatory.append(line)

    # Önerilen bölümü
    onerilen_match = re.search(r'Önerilen:(.+?)(?:\Z)', text, re.DOTALL)
    if onerilen_match:
        lines = onerilen_match.group(1).strip().split('\n')
        for line in lines:
            line = line.strip().lstrip('- •').strip()
            if line and len(line) > 10:
                recommended.append(line)

    return SolutionCriteria(mandatory=mandatory, recommended=recommended)


async def call_llm(prompt: str) -> str:
    if not config.llm_api_key:
        raise RuntimeError("LLM API anahtarı yapılandırılmamış")

    request = {
        "model": config.MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "api_key": config.llm_api_key,
    }
    if config.OPENAI_API_BASE:
        request["api_base"] = config.OPENAI_API_BASE

    response = await litellm.acompletion(
        **request
    )
    return response.choices[0].message.content.strip()


async def search_tree(query: str, tree_for_search: List) -> List[str]:
    search_prompt = f"""
Sen bir İSG (İş Sağlığı ve Güvenliği) uzmanısın.
Aşağıdaki soruyu cevaplamak için hangi node'ların incelenmesi gerektiğini belirle.

Soru: {query}

Doküman ağacı:
{json.dumps(tree_for_search, indent=2, ensure_ascii=False)}

Şu JSON formatında cevap ver:
{{
    "thinking": "hangi node'ların neden ilgili olduğunu açıkla",
    "node_list": ["node_id_1", "node_id_2"]
}}
Sadece JSON döndür, başka bir şey yazma.
"""
    result = await call_llm(search_prompt)
    result = result.strip().replace("```json", "").replace("```", "")
    result_json = json.loads(result)
    return result_json.get("node_list", [])


async def generate_answer(query: str, relevant_content: str) -> str:
    answer_prompt = f"""
Aşağıdaki İSG dokümanı içeriğine dayanarak soruyu Türkçe olarak cevapla.
SADECE verilen içerikteki bilgileri kullan, kendi bilginden ekleme yapma.

Soru: {query}

İlgili içerik:
{relevant_content}

Kapsamlı, profesyonel ve pratik bir cevap ver.
"""
    return await call_llm(answer_prompt)


async def query_rag(
    violation_type: str,
    violation_subtype: str = None,
    process: str = None,
    zone: str = None,
    description: str = None,
    tree: List = None,
    node_map: Dict = None
) -> Dict:
    # Sorgu oluştur
    query_parts = []
    if zone:
        query_parts.append(f"{zone} bölgesinde")
    if process:
        query_parts.append(f"{process} işleminde")
    if violation_subtype:
        query_parts.append(f"{violation_subtype}")
    elif violation_type:
        query_parts.append(f"{violation_type}")
    query_parts.append("için hangi mevzuat uygulanır, riskler ve önlemler nelerdir?")
    query = " ".join(query_parts)

    if description:
        query = f"{description}. {query}"

    # Tree search
    tree_for_search = remove_text(tree)
    node_ids = await search_tree(query, tree_for_search)

    # İçerik çek
    relevant_content = ""
    all_sources = []
    all_regulations = []
    node_titles = []
    similar_incidents = []

    for node_id in node_ids:
        if node_id in node_map:
            node = node_map[node_id]
            text = node.get("text", "")
            relevant_content += f"\n--- {node['title']} ---\n{text}\n"
            node_titles.append(node['title'])

            # Kaynaklar
            sources = extract_sources(text)
            for s in sources:
                s.node = node['title']
                all_sources.append(s)

            # Mevzuat
            regs = extract_regulations(text)
            all_regulations.extend(regs)

            # Benzer olaylar (Benzer Olaylar node'undan)
            if "Benzer Olaylar" in node['title']:
                incidents = re.findall(r'Olay:\s*(.+?)(?:\n|Kök Neden)', text, re.DOTALL)
                similar_incidents.extend([i.strip() for i in incidents])

    # Çözüm kriterleri
    solution_criteria = extract_solution_criteria(relevant_content)

    # Cevap üret
    answer = await generate_answer(query, relevant_content)

    return {
        "query": query,
        "technical_context": relevant_content[:500] + "..." if len(relevant_content) > 500 else relevant_content,
        "similar_incidents": similar_incidents[:3],
        "regulations": all_regulations,
        "solution_criteria": solution_criteria,
        "sources": all_sources,
        "nodes_used": node_titles,
        "answer": answer
    }
