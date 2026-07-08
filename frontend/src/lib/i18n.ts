import { School } from "@/lib/api";

export type Lang = "en" | "ar";

export interface Suggestion {
  icon: string;
  title: string;
  prompt: string;
}

export interface SchoolOption {
  value: School;
  label: string;
  hint: string;
}

export interface Dictionary {
  brandSuffix: string;
  tagline: string;
  newChat: string;
  madhab: string;
  status: string;
  greetingPre: string;
  greetingHi: string;
  emptySubtitle: string;
  thinking: string;
  placeholder: string;
  disclaimer: string;
  copy: string;
  copied: string;
  send: string;
  toggleTheme: string;
  toggleLang: string;
  langName: string; // label shown on the language toggle for the *other* language
  suggestions: Suggestion[];
  schools: SchoolOption[];
}

const en: Dictionary = {
  brandSuffix: "AI",
  tagline: "Your light to Islamic knowledge",
  newChat: "New chat",
  madhab: "Madhab:",
  status: "Answers with scholarly context",
  greetingPre: "Assalamu",
  greetingHi: "Alaikum",
  emptySubtitle:
    "Ask anything about Islamic rulings, the Quran, Hadith, or scholarly opinions. Choose a starting point below or type your own question.",
  thinking: "Noor is reflecting…",
  placeholder: "Ask about Islamic rulings, Quran, Hadith…",
  disclaimer:
    "Noor AI can make mistakes — verify important rulings with a qualified scholar.",
  copy: "Copy",
  copied: "Copied",
  send: "Send question",
  toggleTheme: "Toggle theme",
  toggleLang: "Switch language",
  langName: "العربية",
  suggestions: [
    {
      icon: "🕌",
      title: "Prayer & Worship",
      prompt: "What are the conditions that make a prayer valid?",
    },
    {
      icon: "📖",
      title: "Quran & Tafsir",
      prompt: "Explain the meaning and context of Surah Al-Fatiha.",
    },
    {
      icon: "⚖️",
      title: "Fiqh Rulings",
      prompt: "What is the ruling on combining prayers while travelling?",
    },
    {
      icon: "🌙",
      title: "Fasting",
      prompt: "What invalidates the fast during Ramadan?",
    },
  ],
  schools: [
    { value: "general", label: "All Schools", hint: "Balanced overview" },
    { value: "hanafi", label: "Hanafi", hint: "Abū Ḥanīfa" },
    { value: "maliki", label: "Maliki", hint: "Mālik ibn Anas" },
    { value: "shafii", label: "Shafi'i", hint: "Al-Shāfiʿī" },
    { value: "hanbali", label: "Hanbali", hint: "Ibn Ḥanbal" },
  ],
};

const ar: Dictionary = {
  brandSuffix: "الذكاء",
  tagline: "نورك إلى المعرفة الإسلامية",
  newChat: "محادثة جديدة",
  madhab: "المذهب:",
  status: "إجابات مع سياق علمي",
  greetingPre: "السلام",
  greetingHi: "عليكم",
  emptySubtitle:
    "اسأل أي شيء عن الأحكام الشرعية، القرآن، الحديث، أو آراء العلماء. اختر نقطة بداية أدناه أو اكتب سؤالك.",
  thinking: "نور يتأمّل…",
  placeholder: "اسأل عن الأحكام الشرعية، القرآن، الحديث…",
  disclaimer: "قد يخطئ نور — تحقّق من الأحكام المهمة مع عالمٍ مختص.",
  copy: "نسخ",
  copied: "تم النسخ",
  send: "إرسال السؤال",
  toggleTheme: "تبديل السمة",
  toggleLang: "تغيير اللغة",
  langName: "English",
  suggestions: [
    {
      icon: "🕌",
      title: "الصلاة والعبادة",
      prompt: "ما هي شروط صحّة الصلاة؟",
    },
    {
      icon: "📖",
      title: "القرآن والتفسير",
      prompt: "اشرح معنى وسياق سورة الفاتحة.",
    },
    {
      icon: "⚖️",
      title: "أحكام الفقه",
      prompt: "ما حكم الجمع بين الصلاتين أثناء السفر؟",
    },
    {
      icon: "🌙",
      title: "الصيام",
      prompt: "ما الذي يُبطل الصيام في رمضان؟",
    },
  ],
  schools: [
    { value: "general", label: "جميع المذاهب", hint: "نظرة متوازنة" },
    { value: "hanafi", label: "الحنفي", hint: "أبو حنيفة" },
    { value: "maliki", label: "المالكي", hint: "مالك بن أنس" },
    { value: "shafii", label: "الشافعي", hint: "الإمام الشافعي" },
    { value: "hanbali", label: "الحنبلي", hint: "ابن حنبل" },
  ],
};

export const translations: Record<Lang, Dictionary> = { en, ar };