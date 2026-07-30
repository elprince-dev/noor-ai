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
  stop: string;
  regenerate: string;
  exportChat: string;
  sourceChips: string[];
  toolLabels: Record<string, string>;
  resultsCount: (n: number) => string;
  toggleTheme: string;
  toggleLang: string;
  langName: string; // label shown on the language toggle for the *other* language
  // ── Sidebar / history ──
  history: string;
  searchChats: string;
  noChats: string;
  noChatsHint: string;
  noResults: string;
  today: string;
  yesterday: string;
  last7Days: string;
  older: string;
  deleteChat: string;
  renameChat: string;
  clearAll: string;
  clearAllConfirm: string;
  openSidebar: string;
  closeSidebar: string;
  collapseSidebar: string;
  messagesCount: (n: number) => string;
  // ── Composer / misc ──
  enterHint: string;
  shiftEnterHint: string;
  scrollToBottom: string;
  you: string;
  keyboardShortcut: string;
  freePlan: string;
  guestUser: string;
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
  stop: "Stop generating",
  regenerate: "Regenerate",
  exportChat: "Export chat",
  sourceChips: ["📖 The Noble Qur'an", "📜 Sahih al-Bukhari", "📜 Sahih Muslim", "⚖️ 4 Madhabs"],
  toolLabels: {
    search_quran: "Searching the Qur'an",
    search_hadith: "Searching Sahih al-Bukhari & Muslim",
  },
  resultsCount: (n) => `${n} result${n === 1 ? "" : "s"}`,
  toggleTheme: "Toggle theme",
  toggleLang: "Switch language",
  langName: "العربية",
  history: "Chats",
  searchChats: "Search chats…",
  noChats: "No conversations yet",
  noChatsHint: "Your chats will appear here.",
  noResults: "No chats match your search.",
  today: "Today",
  yesterday: "Yesterday",
  last7Days: "Previous 7 days",
  older: "Older",
  deleteChat: "Delete chat",
  renameChat: "Rename chat",
  clearAll: "Clear all chats",
  clearAllConfirm: "Delete all conversations? This cannot be undone.",
  openSidebar: "Open sidebar",
  closeSidebar: "Close sidebar",
  collapseSidebar: "Collapse sidebar",
  messagesCount: (n) => `${n} message${n === 1 ? "" : "s"}`,
  enterHint: "to send",
  shiftEnterHint: "for a new line",
  scrollToBottom: "Scroll to latest",
  you: "You",
  keyboardShortcut: "Ctrl + K for new chat",
  freePlan: "Preview",
  guestUser: "Guest",
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
  stop: "إيقاف التوليد",
  regenerate: "إعادة التوليد",
  exportChat: "تصدير المحادثة",
  sourceChips: ["📖 القرآن الكريم", "📜 صحيح البخاري", "📜 صحيح مسلم", "⚖️ المذاهب الأربعة"],
  toolLabels: {
    search_quran: "البحث في القرآن الكريم",
    search_hadith: "البحث في الصحيحين",
  },
  resultsCount: (n) => `${n} ${n === 1 ? "نتيجة" : "نتائج"}`,
  toggleTheme: "تبديل السمة",
  toggleLang: "تغيير اللغة",
  langName: "English",
  history: "المحادثات",
  searchChats: "ابحث في المحادثات…",
  noChats: "لا توجد محادثات بعد",
  noChatsHint: "ستظهر محادثاتك هنا.",
  noResults: "لا توجد محادثات مطابقة لبحثك.",
  today: "اليوم",
  yesterday: "أمس",
  last7Days: "آخر ٧ أيام",
  older: "أقدم",
  deleteChat: "حذف المحادثة",
  renameChat: "إعادة تسمية",
  clearAll: "حذف كل المحادثات",
  clearAllConfirm: "هل تريد حذف جميع المحادثات؟ لا يمكن التراجع عن هذا.",
  openSidebar: "فتح الشريط الجانبي",
  closeSidebar: "إغلاق الشريط الجانبي",
  collapseSidebar: "طيّ الشريط الجانبي",
  messagesCount: (n) => `${n} ${n === 1 ? "رسالة" : "رسائل"}`,
  enterHint: "للإرسال",
  shiftEnterHint: "لسطر جديد",
  scrollToBottom: "الانتقال إلى الأحدث",
  you: "أنت",
  keyboardShortcut: "Ctrl + K لمحادثة جديدة",
  freePlan: "معاينة",
  guestUser: "زائر",
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
