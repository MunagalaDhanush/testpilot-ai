import { NextRequest, NextResponse } from 'next/server';
import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

const SYSTEM_PROMPT = `You are TestPilot Assistant, embedded in the TestPilot AI dashboard. TestPilot AI is a production-grade multi-agent automated test generation platform.

Architecture:
- GitHub webhooks trigger the pipeline
- n8n handles webhook routing
- FastAPI orchestrates the multi-agent workflow
- LangGraph manages the agent graph execution
- Six specialized AI agents collaborate:
  * Context Collector (Claude Haiku) — reads PR diff and identifies changed functions
  * Risk Classifier (Claude Haiku) — assesses risk level (low/medium/high/critical)
  * Test Strategist (Claude Sonnet) — plans test coverage strategy
  * Test Generator (Claude Sonnet) — writes pytest unit, integration, and API test files
  * Failure Diagnostician (Claude Sonnet) — repairs failing tests (up to 3 attempts)
  * PR Summarizer (Claude Haiku) — writes summary comment for the GitHub PR
- Tests run in Docker sandboxes for isolation
- Results stored in PostgreSQL
- Artifacts stored in AWS S3
- Job queue managed via AWS SQS
- Model routing: Haiku for fast structured tasks, Sonnet for reasoning-heavy tasks (approximately 60% cost savings)
- Human-in-the-loop: jobs enter "awaiting_review" state before any PR comment is posted

Answer questions clearly and concisely. Use technical language appropriate for developers. Do not use emoji in responses. Keep answers under 150 words unless more detail is genuinely needed.`;

export async function POST(req: NextRequest): Promise<NextResponse> {
  try {
    const body = await req.json();
    const messages: Array<{ role: 'user' | 'assistant'; content: string }> = body.messages ?? [];
    const jobContext: string | undefined = body.jobContext;

    if (!messages.length || !messages[messages.length - 1].content.trim()) {
      return NextResponse.json({ error: 'No message provided' }, { status: 400 });
    }

    const systemPrompt = jobContext
      ? `${SYSTEM_PROMPT}\n\nCurrent context: ${jobContext}`
      : SYSTEM_PROMPT;

    const response = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 500,
      system: systemPrompt,
      messages,
    });

    const text = response.content
      .filter((b): b is Anthropic.TextBlock => b.type === 'text')
      .map((b) => b.text)
      .join('');

    return NextResponse.json({ message: text });
  } catch (e) {
    console.error('Chat API error:', e);
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Internal server error' },
      { status: 500 }
    );
  }
}
