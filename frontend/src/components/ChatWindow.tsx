"use client";

import { useEffect, useRef } from "react";
import { Message } from "@/app/page";
import { MessageBubble } from "./MessageBubble";

interface ChatWindowProps {
  messages: Message[];
  loading: boolean;
}

export function ChatWindow({ messages, loading }: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  if (messages.length === 0 && !loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400">
        <div className="text-center">
          <p className="text-lg mb-2">Assalamu Alaikum! 👋</p>
          <p className="text-sm">Ask me anything about Islamic rulings, Quran, or Hadith.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto space-y-3">
      {messages.map((msg, i) => (
        <MessageBubble key={i} message={msg} />
      ))}
      {loading && (
        <div className="bg-gray-100 p-4 rounded-lg mr-12 animate-pulse">
          <div className="flex items-center gap-2 text-gray-500">
            <span className="text-sm">Thinking...</span>
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
