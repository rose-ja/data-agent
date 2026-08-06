/**
 * 前端应用主组件
 * 负责聊天会话状态、SSE 事件消费和整体页面布局
 */
import {
  Activity,
  BarChart3,
  Eraser,
  History,
  Leaf,
  MessageSquarePlus,
  Server,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Composer } from './components/Composer';
import { EmptyState } from './components/EmptyState';
import { MessageBubble } from './components/MessageBubble';
import { streamQuery } from './lib/agentApi';
import { cn, summarizeResult } from './lib/format';
import type { AgentEvent, ChatMessage, StepState } from './types/agent';

const examples = [
  '统计 2025 年第一季度各大区的 GMV，并按 GMV 从高到低排序',
  '统计 2025 年 3 月各商品品类的销量和销售额',
  '查询华东地区 2025 年第一季度销售额最高的前 5 个商品',
  '按会员等级统计 2025 年第一季度的订单数和销售额',
];

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'Vite /api proxy';

function makeId() {
  return (
    crypto.randomUUID?.() ??
    `${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

function upsertStep(
  steps: StepState[] = [],
  event: Extract<AgentEvent, { type: 'progress' }>,
) {
  const next = steps.filter((item) => item.step !== event.step);
  next.push({
    step: event.step,
    status: event.status,
    updatedAt: Date.now(),
  });
  return next;
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [activeController, setActiveController] =
    useState<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const isStreaming = Boolean(activeController);
  const canSubmit = draft.trim().length > 0 && !isStreaming;

  const completedCount = useMemo(
    () =>
      messages.filter(
        (message) => message.role === 'assistant' && message.status === 'done',
      ).length,
    [messages],
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages]);

  const startQuery = async (rawQuery = draft) => {
    const query = rawQuery.trim();
    if (!query || isStreaming) return;

    const userMessage: ChatMessage = {
      id: makeId(),
      role: 'user',
      content: query,
      createdAt: Date.now(),
    };

    const assistantId = makeId();
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '正在连接问数智能体...',
      createdAt: Date.now(),
      status: 'streaming',
      steps: [],
    };

    const controller = new AbortController();
    setActiveController(controller);
    setDraft('');
    setMessages((current) => [...current, userMessage, assistantMessage]);

    const onEvent = (event: AgentEvent) => {
      setMessages((current) =>
        current.map((message) => {
          if (message.id !== assistantId) return message;

          if (event.type === 'progress') {
            return {
              ...message,
              content:
                event.status === 'running'
                  ? `正在执行：${event.step}`
                  : message.content,
              steps: upsertStep(message.steps, event),
            };
          }

          if (event.type === 'result') {
            return {
              ...message,
              status: 'done',
              content: summarizeResult(event.data),
              result: event.data,
            };
          }

          return {
            ...message,
            status: 'error',
            content: '这次查询没有成功。',
            error: event.message,
          };
        }),
      );
    };

    try {
      await streamQuery(query, {
        signal: controller.signal,
        onEvent,
      });
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        onEvent({ type: 'error', message: '已停止生成。' });
      } else {
        onEvent({ type: 'error', message: (error as Error).message });
      }
    } finally {
      setActiveController(null);
    }
  };

  const stop = () => {
    activeController?.abort();
  };

  const reset = () => {
    setMessages([]);
    setDraft('');
  };

  return (
    <div className='flex min-h-screen flex-col bg-parchment text-ink'>
      {/* 顶部导航 */}
      <header className='flex items-center justify-between border-b border-ink/10 bg-parchment/85 px-4 py-3 backdrop-blur'>
        <div className='flex items-center gap-3'>
          <div className='grid h-9 w-9 place-items-center bg-ink text-parchment'>
            <Leaf className='h-5 w-5' aria-hidden='true' />
          </div>
          <div className='text-sm font-semibold'>Shopkeeper Agent</div>
        </div>
        <div className='flex items-center gap-3 text-xs text-ink/55'>
          <span className='hidden items-center gap-1 sm:inline-flex'>
            <Server className='h-3.5 w-3.5' aria-hidden='true' />
            {API_BASE_URL}
          </span>
          <span className='hidden items-center gap-1 sm:inline-flex'>
            <Activity className='h-3.5 w-3.5' aria-hidden='true' />
            {completedCount} 次查询
          </span>
          <button
            type='button'
            onClick={reset}
            className='flex items-center gap-1 rounded-full border border-ink/15 px-3 py-1.5 transition hover:bg-ink/5'
          >
            <Eraser className='h-3.5 w-3.5' aria-hidden='true' />
            清空
          </button>
        </div>
      </header>

      {/* 消息区 */}
      <main
        ref={scrollRef}
        className='mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 overflow-y-auto px-4 py-8'
      >
        {messages.length === 0 ? (
          <EmptyState examples={examples} onUseExample={startQuery} />
        ) : (
          messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))
        )}
      </main>

      {/* 输入区 */}
      <Composer
        value={draft}
        disabled={!canSubmit}
        isStreaming={isStreaming}
        onChange={setDraft}
        onSubmit={() => startQuery()}
        onStop={stop}
      />
    </div>
  );
}
