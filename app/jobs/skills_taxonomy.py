"""Deterministic skills taxonomy for semantic-ish skill matching.

Real semantic matching would need embeddings/an LLM, but the project
philosophy (section 36) says: prefer deterministic code, use LLMs only where
they add real value, and never let core filtering *depend* entirely on an
LLM. This module gives us a fast, offline, always-available first pass:

- Exact match (case-insensitive) -> full credit.
- Same "cluster" (e.g. pytorch/tensorflow/scikit-learn/keras are all
  "ml-frameworks") -> partial credit, since they're adjacent/transferable
  skills, not identical ones.
- Unknown/unrelated -> no credit; a real gap.

The LLM (when configured) is used only as an additional, strictly
score-reducing-or-neutral secondary opinion for skills that don't match
here at all - see matcher.llm_semantic_skill_check. It can never invent an
exact match; it can only optionally grant partial credit if it judges two
tools/frameworks as genuinely related.
"""
from __future__ import annotations

# Each cluster groups tools/frameworks/languages that are meaningfully
# transferable/adjacent to each other. Add to these lists as your own stack
# grows - this is intentionally small and explicit rather than trying to be
# an exhaustive ontology.
SKILL_CLUSTERS: list[set[str]] = [
    {"python", "python3"},
    {"pytorch", "tensorflow", "keras", "scikit-learn", "sklearn", "xgboost", "lightgbm"},
    {"numpy", "pandas", "scipy"},
    {"machine learning", "ml", "deep learning", "dl", "artificial intelligence", "ai"},
    {"nlp", "natural language processing", "spacy", "nltk", "huggingface", "transformers"},
    {"computer vision", "cv", "opencv"},
    {"fastapi", "flask", "django", "starlette"},
    {"rest", "rest api", "restful", "rest apis"},
    {"graphql", "apollo"},
    {"docker", "containerization", "podman"},
    {"kubernetes", "k8s", "helm"},
    {"postgresql", "postgres", "mysql", "mariadb", "sqlite"},
    {"mongodb", "nosql", "dynamodb", "cassandra"},
    {"redis", "memcached"},
    {"aws", "amazon web services", "ec2", "s3", "lambda"},
    {"gcp", "google cloud", "google cloud platform"},
    {"azure", "microsoft azure"},
    {"git", "github", "gitlab", "version control"},
    {"ci/cd", "cicd", "jenkins", "github actions", "gitlab ci"},
    {"react", "reactjs", "react.js"},
    {"vue", "vuejs", "vue.js"},
    {"angular", "angularjs"},
    {"javascript", "js", "typescript", "ts"},
    {"node", "nodejs", "node.js", "express"},
    {"java", "spring", "spring boot"},
    {"c++", "cpp"},
    {"c#", "csharp", ".net", "dotnet"},
    {"golang", "go"},
    {"sql", "mysql", "postgresql", "t-sql", "plsql"},
    {"data engineering", "etl", "airflow", "dbt", "spark", "pyspark", "kafka"},
    {"linux", "unix", "bash", "shell scripting"},
]

_SKILL_TO_CLUSTER: dict[str, int] = {}
for _idx, _cluster in enumerate(SKILL_CLUSTERS):
    for _skill in _cluster:
        _SKILL_TO_CLUSTER[_skill] = _idx


def normalize(skill: str) -> str:
    return skill.strip().lower()


def are_related(skill_a: str, skill_b: str) -> bool:
    """True if two skills are in the same taxonomy cluster (adjacent/
    transferable), False if unknown or unrelated."""
    a, b = normalize(skill_a), normalize(skill_b)
    if a == b:
        return True
    cluster_a = _SKILL_TO_CLUSTER.get(a)
    cluster_b = _SKILL_TO_CLUSTER.get(b)
    if cluster_a is None or cluster_b is None:
        return False
    return cluster_a == cluster_b


def find_related_candidate_skill(job_skill: str, candidate_skills: set[str]) -> str | None:
    """Return the candidate skill (if any) that is related to job_skill via
    the taxonomy, or None if no related skill is found."""
    job_skill_norm = normalize(job_skill)
    for candidate_skill in candidate_skills:
        if are_related(job_skill_norm, candidate_skill):
            return candidate_skill
    return None
