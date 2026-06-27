import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / 'system_prompt.md'


def _load_system_prompt():
    try:
        return SYSTEM_PROMPT_PATH.read_text()
    except Exception as e:
        logger.warning(f'Failed to load system prompt: {e}')
        return ''


class LLMProvider:
    def __init__(self, provider: str = None):
        self.provider = (provider or os.getenv('AI_PROVIDER', 'openrouter')).lower()
        self.api_key = os.getenv('AI_API_KEY', '')
        self.model = os.getenv('AI_MODEL', '')
        self.base_url = os.getenv('AI_BASE_URL', '')

        if not self.api_key:
            raise ValueError(f'AI_API_KEY not set for provider={self.provider}')

        self._set_defaults()

    def _set_defaults(self):
        if self.provider == 'openai':
            self.base_url = self.base_url or 'https://api.openai.com/v1'
            self.model = self.model or 'gpt-4o'
        elif self.provider == 'anthropic':
            self.base_url = self.base_url or 'https://api.anthropic.com/v1'
            self.model = self.model or 'claude-sonnet-4-20250514'
        elif self.provider == 'openrouter':
            self.base_url = self.base_url or 'https://openrouter.ai/api/v1'
            self.model = self.model or 'anthropic/claude-sonnet-4-20250514'
        else:
            raise ValueError(f'Unknown provider: {self.provider}')

    def _build_messages(self, notice: dict) -> list:
        system_prompt = _load_system_prompt()
        scoring_prompt = f"""
Analyze the following procurement opportunity and produce a JSON response with these exact keys:
{{
  "opportunity_score": <0-100>,
  "strategic_fit": <0-30>,
  "geographic_fit": <0-15>,
  "past_performance_fit": <0-15>,
  "win_probability": <0-20>,
  "revenue_potential": <0-10>,
  "strategic_relationship_value": <0-10>,
  "relevant_unit": "<Nextier Advisory|Nextier SPD|Nextier Power|Nextier Liberia|Multiple Units>",
  "suggested_position": "<Pursue Immediately|Pursue with Consortium|Monitor|Decline>",
  "opportunity_type": "<Consulting Contract|Research Opportunity|Development Project|Energy Project|Security and Peacebuilding Project|Other>",
  "funding_organization": "<name>",
  "geography": "<country or region>",
  "submission_deadline": "<date or null>",
  "estimated_budget": "<estimate or null>",
  "red_flags": ["<flag1>", ...],
  "consortium_possible": true|false,
  "consortium_role": "<role or null>",
  "why_it_fits": "<detailed rationale>",
  "risks": "<concerns>",
  "executive_summary": "<max 250 words>"
}}

OPPORTUNITY DATA:
Title: {notice.get('title', 'N/A')}
Organization: {notice.get('organization', 'N/A')}
Country: {notice.get('country', 'N/A')}
Description: {notice.get('description', 'N/A')[:3000]}
Source: {notice.get('source', 'N/A')}
URL: {notice.get('url', 'N/A')}
Published: {notice.get('published', 'N/A')}
Deadline: {notice.get('deadline', 'N/A')}
Reference: {notice.get('reference', 'N/A')}

Respond with ONLY the JSON object. No markdown, no explanation."""
        if self.provider == 'anthropic':
            return [
                {'role': 'user', 'content': f'{system_prompt}\n\n---\n\n{scoring_prompt}'}
            ]
        return [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': scoring_prompt},
        ]

    def analyze(self, notice: dict, timeout: int = 60) -> dict:
        import httpx

        messages = self._build_messages(notice)
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
        }
        if self.provider == 'openrouter':
            headers['HTTP-Referer'] = 'https://bidhunter.nextier.com'
            headers['X-Title'] = 'Nextier Opportunity Finder'

        body = {
            'model': self.model,
            'max_tokens': 4096,
            'temperature': 0.1,
        }

        if self.provider == 'anthropic':
            body['messages'] = messages
            body['system'] = _load_system_prompt()
            body['messages'] = [{'role': 'user', 'content': messages[0]['content'].replace(_load_system_prompt() + '\n\n---\n\n', '')}]
        else:
            body['messages'] = messages

        try:
            with httpx.Client(timeout=timeout) as client:
                url = f'{self.base_url.rstrip("/")}/chat/completions'
                if self.provider == 'anthropic':
                    url = f'{self.base_url.rstrip("/")}/messages'

                resp = client.post(url, json=body, headers=headers)

                if resp.status_code == 429:
                    logger.warning(f'Rate limited, retrying in 3s...')
                    import time
                    time.sleep(3)
                    resp = client.post(url, json=body, headers=headers)

                if resp.status_code != 200:
                    logger.error(f'LLM API error {resp.status_code}: {resp.text[:500]}')
                    return self._fallback_analysis(notice, f'API error: {resp.status_code}')

                data = resp.json()
                content = ''
                if self.provider == 'anthropic':
                    for c in data.get('content', []):
                        if c.get('type') == 'text':
                            content = c['text']
                            break
                else:
                    content = data['choices'][0]['message']['content']

                return self._parse_response(content, notice)

        except httpx.TimeoutException:
            logger.warning(f'LLM timeout for {notice.get("noticeId", notice.get("id"))}')
            return self._fallback_analysis(notice, 'timeout')
        except Exception as e:
            logger.exception(f'LLM analysis failed: {e}')
            return self._fallback_analysis(notice, str(e))

    def _parse_response(self, content: str, notice: dict) -> dict:
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                result = json.loads(json_match.group())
            except json.JSONDecodeError:
                return self._fallback_analysis(notice, 'invalid JSON')
        else:
            return self._fallback_analysis(notice, 'no JSON found')

        return {
            'notice_id': notice.get('noticeId', notice.get('notice_id', '')),
            'title': notice.get('title', ''),
            'organization': notice.get('organization', ''),
            'country': notice.get('country', ''),
            'source': notice.get('source', ''),
            'url': notice.get('url', ''),
            'score': max(0, min(100, result.get('opportunity_score', 0))),
            'strategic_fit': result.get('strategic_fit', 0),
            'geographic_fit': result.get('geographic_fit', 0),
            'past_performance_fit': result.get('past_performance_fit', 0),
            'win_probability': result.get('win_probability', 0),
            'revenue_potential': result.get('revenue_potential', 0),
            'strategic_relationship_value': result.get('strategic_relationship_value', 0),
            'relevant_unit': result.get('relevant_unit', 'Nextier Advisory'),
            'suggested_position': result.get('suggested_position', 'Monitor'),
            'opportunity_type': result.get('opportunity_type', 'Other'),
            'funding_organization': result.get('funding_organization', ''),
            'geography': result.get('geography', ''),
            'submission_deadline': result.get('submission_deadline', ''),
            'estimated_budget': result.get('estimated_budget', ''),
            'red_flags': result.get('red_flags', []),
            'consortium_possible': result.get('consortium_possible', False),
            'consortium_role': result.get('consortium_role', ''),
            'why_it_fits': result.get('why_it_fits', ''),
            'risks': result.get('risks', ''),
            'executive_summary': result.get('executive_summary', ''),
            'model_used': self.model,
            'provider': self.provider,
        }

    def _fallback_analysis(self, notice: dict, reason: str) -> dict:
        score = 25
        country = (notice.get('country') or '').lower()
        if 'nigeria' in country or 'liberia' in country:
            score = 50
        title = (notice.get('title') or '').lower()
        if any(kw in title for kw in ['consult', 'advisory', 'policy', 'governance', 'research']):
            score += 10

        return {
            'notice_id': notice.get('noticeId', notice.get('notice_id', '')),
            'title': notice.get('title', ''),
            'organization': notice.get('organization', ''),
            'country': notice.get('country', ''),
            'source': notice.get('source', ''),
            'url': notice.get('url', ''),
            'score': min(score, 100),
            'strategic_fit': 0,
            'geographic_fit': 0,
            'past_performance_fit': 0,
            'win_probability': 0,
            'revenue_potential': 0,
            'strategic_relationship_value': 0,
            'relevant_unit': 'Nextier Advisory',
            'suggested_position': 'Monitor',
            'opportunity_type': 'Other',
            'funding_organization': notice.get('organization', ''),
            'geography': notice.get('country', ''),
            'submission_deadline': '',
            'estimated_budget': '',
            'red_flags': [],
            'consortium_possible': False,
            'consortium_role': '',
            'why_it_fits': f'Fallback analysis (LLM unavailable: {reason}). Basic score based on country match.',
            'risks': 'Unable to assess due to LLM unavailability.',
            'executive_summary': f'LLM analysis unavailable ({reason}). Defaulting to heuristic scoring.',
            'model_used': 'fallback',
            'provider': 'fallback',
        }
