"use client";

import { useState, useEffect, useRef } from "react";
import { apiClient, School, AskResponse } from "@/lib/api";
import { ChatWindow } from "@/components/ChatWindow";
import { SchoolSelector } from "@/components/SchoolSelector";

export interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string>("");
  const [school, setSchool] = useState<School>("general");
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    apiClient.createSession().then((res) => setSessionId(res.session_id));
  }, []);

  const handleSend = async () => {
    if (!input.trim() || !sessionId || loading) return;

    const userMessage: Message = { role: "user", content: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    try {
      const response: AskResponse = await apiClient.ask({
        question: input,
        session_id: sessionId,
        school,
      });
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: response.answer },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Sorry, an error occurred. Please try again." },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleNewSession = async () => {
    const res = await apiClient.createSession();
    setSessionId(res.session_id);
    setMessages([]);
  };

  return (
    <main className="flex flex-col h-screen max-w-3xl mx-auto p-4">
      {/* Header */}
      <div className="text-center mb-4">
        <h1 className="text-3xl font-bold text-emerald-700">🌙 Noor AI</h1>
        <p className="text-gray-500 text-sm">Your light to Islamic knowledge</p>
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between mb-4">
        <SchoolSelector value={school} onChange={setSchool} />
        <button
          onClick={handleNewSession}
          className="text-sm text-gray-500 hover:text-gray-700 underline"
        >
          New conversation
        </button>
      </div>

      {/* Chat */}
      <ChatWindow messages={messages} loading={loading} />

      {/* Input */}
      <div className="flex gap-2 mt-4">
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Ask about Islamic rulings, Quran, Hadith..."
          className="flex-1 border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-500"
          disabled={loading}
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-300 text-white px-6 py-2 rounded-lg font-medium transition-colors"
        >
          Ask
        </button>
      </div>
    </main>
  );
}
