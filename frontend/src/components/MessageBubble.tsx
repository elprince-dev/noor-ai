"use client";

import { Message } from "@/app/page";

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] p-4 rounded-lg whitespace-pre-wrap text-sm leading-relaxed ${
          isUser
            ? "bg-emerald-600 text-white rounded-br-none"
            : "bg-white border border-gray-200 text-gray-800 rounded-bl-none shadow-sm"
        }`}
      >
        {message.content}
      </div>
    </div>
  );
}
