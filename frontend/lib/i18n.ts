export type Lang = "hi" | "en";

const strings = {
  newSale: { hi: "नई बिक्री", en: "New sale" },
  myCard: { hi: "मेरा कार्ड", en: "My card" },
  wallet: { hi: "कमाई", en: "Wallet" },
  score: { hi: "स्कोर", en: "Score" },
  credits: { hi: "क्रेडिट", en: "credits" },
  whatScrap: { hi: "कौन सा कबाड़?", en: "What are you selling?" },
  howMuch: { hi: "कितना वज़न?", en: "About how much?" },
  takePhoto: { hi: "फ़ोटो लें", en: "Take a photo" },
  retake: { hi: "दोबारा लें", en: "Retake" },
  send: { hi: "भेजें", en: "Send" },
  showQr: { hi: "डीलर को अपना QR दिखाएँ", en: "Show your QR to the dealer" },
  expiresIn: { hi: "बचा समय", en: "Expires in" },
  accepted: { hi: "डीलर ने स्वीकार किया — तौल हो रहा है", en: "Dealer accepted — weighing now" },
  weighed: { hi: "तौल हो गया", en: "Weighed" },
  paying: { hi: "UPI से पैसा आ रहा है…", en: "UPI payment on its way…" },
  received: { hi: "मिले", en: "received" },
  done: { hi: "ठीक है", en: "Done" },
  expired: { hi: "समय खत्म। फिर से भेजें।", en: "Request expired. Please send again." },
  dupPhoto: { hi: "यह फ़ोटो पहले इस्तेमाल हो चुकी है", en: "This photo was already used" },
  dupPhotoHelp: { hi: "अभी के कबाड़ की नई फ़ोटो लें।", en: "Take a fresh photo of today's scrap." },
  loanUnlocked: { hi: "पहला लोन खुल गया", en: "Starter loan unlocked" },
  loanIn: { hi: "और बिक्री के बाद लोन खुलेगा", en: "more sales to unlock a loan" },
  recentSales: { hi: "हाल की बिक्री", en: "Recent sales" },
  thisMonth: { hi: "पिछले 30 दिन", en: "Last 30 days" },
  messages: { hi: "संदेश", en: "Messages" },
  cardHelp: { hi: "कार्ड प्रिंट करके भी चल सकता है", en: "Works printed, too" },
  homeHello: { hi: "नमस्ते", en: "Hello" },
} as const;

export type Key = keyof typeof strings;
export const t = (lang: Lang, key: Key) => strings[key][lang];

/** What the speaker button reads out on each screen. */
export const voice = {
  home: { hi: "नई बिक्री के लिए हरा बटन दबाएँ।", en: "Press the green button to make a new sale." },
  sale: {
    hi: "कबाड़ चुनें, वज़न खिसकाएँ, फिर फ़ोटो लेकर भेजें।",
    en: "Pick the scrap, slide to the weight, take a photo and send.",
  },
  waiting: { hi: "डीलर को अपना QR कार्ड दिखाएँ।", en: "Show your QR card to the dealer." },
};
