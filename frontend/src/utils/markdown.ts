import DOMPurify from 'dompurify';
import { marked } from 'marked';

marked.setOptions({
  breaks: true,
  gfm: true,
});

/**
 * Render markdown to sanitized HTML.
 *
 * Anti-hallucination layer L4 passes raw query results through the LLM, so
 * model output (and graph data values embedded in it) flows straight into
 * this render path. DOMPurify strips scripts / event handlers / javascript:
 * URLs before the string reaches v-html.
 */
export function renderMarkdown(content: string): string {
  const html = marked.parse(content, { async: false }) as string;
  return DOMPurify.sanitize(html);
}
