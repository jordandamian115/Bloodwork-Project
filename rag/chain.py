from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.chains.retrieval import create_retrieval_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from config.settings import get_settings
from security.responsible_ai import MEDICAL_DISCLAIMER, grounding_instruction


def build_qa_chain(vectorstore):
    settings = get_settings()
    llm = ChatOllama(model=settings.ollama_model, temperature=0)

    prompt = ChatPromptTemplate.from_template(
        """You are an educational bloodwork literacy assistant for a RAG portfolio system.

{disclaimer}

{grounding}

Structured lab findings (already de-identified; demographics are bands only):
{lab_context}

Retrieved scientific context:
{context}

Question: {input}

Respond with:
1. ONLY discuss the structured findings listed below. Do not enumerate other bloodwork markers.
2. Compare those findings to literature ranges **only if those ranges appear in the retrieved context**
3. Possible health themes the papers associate with those findings (not a diagnosis)
4. Evidence-based discussion points from the context for those findings: diet/lifestyle **and** medications or supplements the papers actually mention
5. What must go through a licensed clinician
6. Gaps: what you cannot say because the sources do not cover it
"""
    )

    doc_chain = create_stuff_documents_chain(llm, prompt)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
    return create_retrieval_chain(retriever, doc_chain)


def chain_inputs(question: str, lab_context: str) -> dict:
    return {
        "input": question,
        "lab_context": lab_context or "No structured lab panel is loaded.",
        "disclaimer": MEDICAL_DISCLAIMER,
        "grounding": grounding_instruction(),
    }
