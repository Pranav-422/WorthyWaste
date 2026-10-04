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
  // Photo check
  photoMismatch: { hi: "फ़ोटो और चुना हुआ कबाड़ अलग लग रहे हैं", en: "The photo and your choice look different" },
  changeMaterial: { hi: "कबाड़ बदलें", en: "Change material" },
  sendAnyway: { hi: "फिर भी भेजें", en: "Send anyway" },
  youChose: { hi: "आपने चुना", en: "You chose" },
  // Choosing a shop
  chooseShop: { hi: "किस दुकान पर बेच रहे हैं?", en: "Which shop are you selling to?" },
  lastUsed: { hi: "पिछली बार यहीं", en: "last time" },
  noShopsNearby: { hi: "5 किलोमीटर में कोई दुकान नहीं मिली", en: "No registered shop within 5 km" },
  away: { hi: "दूर", en: "away" },
  // My requests, and the waiting timeline
  myRequests: { hi: "मेरे अनुरोध", en: "My requests" },
  noRequests: { hi: "अभी कोई अनुरोध नहीं", en: "No requests yet" },
  cancel: { hi: "रद्द करें", en: "Cancel" },
  cancelled: { hi: "रद्द कर दिया", en: "Cancelled" },
  stepSent: { hi: "भेजा", en: "Sent" },
  stepAccepted: { hi: "स्वीकार", en: "Accepted" },
  stepWeighed: { hi: "तौला", en: "Weighed" },
  stepPaying: { hi: "पैसा भेजा जा रहा है", en: "Paying" },
  stepPaid: { hi: "पैसा मिला", en: "Paid" },
  sellingTo: { hi: "दुकान", en: "Shop" },
  // What the photo check saw, when it is not one of the six materials
  aiMixed: { hi: "मिला-जुला कबाड़", en: "a mixed load" },
  aiNotScrap: { hi: "कबाड़ नहीं", en: "Not scrap" },
  aiScreen: { hi: "स्क्रीन की फ़ोटो", en: "A photo of a screen" },
  // GPS
  locationDenied: { hi: "फ़ोन की जगह (GPS) बंद है", en: "Location is turned off" },
  locationDeniedHelp: {
    hi: "सेटिंग में इस ऐप को जगह देखने की इजाज़त दें, फिर दोबारा भेजें। डीलर के पास होना ज़रूरी है।",
    en: "Allow this app to use your location in settings, then send again. You must be at the dealer.",
  },
  locationTimeout: { hi: "जगह नहीं मिल पाई", en: "Could not find your location" },
  locationTimeoutHelp: {
    hi: "खुली जगह पर जाकर दोबारा कोशिश करें।",
    en: "Step outside or into the open and try again.",
  },
} as const;

export type Key = keyof typeof strings;
export const t = (lang: Lang, key: Key) => strings[key][lang];

// What the app says when the photo check disagrees with the material the collector picked.
// One fixed line per material, pre-recorded by scripts/make_audio.py — the text here is the clip's
// key, so it must match MISMATCH_CLIPS there exactly.
const mismatchByMaterial: Record<Lang, Record<string, string>> = {
  hi: {
    plastic: "ये प्लास्टिक बोतल लग रही है — सही चुनें या फिर से फ़ोटो लें",
    cardboard: "ये गत्ता लग रहा है — सही चुनें या फिर से फ़ोटो लें",
    metal: "ये डिब्बे या टिन लग रहे हैं — सही चुनें या फिर से फ़ोटो लें",
    paper: "ये अखबार लग रहा है — सही चुनें या फिर से फ़ोटो लें",
    wire: "ये तार लग रहा है — सही चुनें या फिर से फ़ोटो लें",
    glass: "ये कांच लग रहा है — सही चुनें या फिर से फ़ोटो लें",
  },
  en: {
    plastic: "This looks like plastic bottles — pick the right one or take the photo again",
    cardboard: "This looks like cardboard — pick the right one or take the photo again",
    metal: "This looks like cans or tin — pick the right one or take the photo again",
    paper: "This looks like newspaper — pick the right one or take the photo again",
    wire: "This looks like wire — pick the right one or take the photo again",
    glass: "This looks like glass — pick the right one or take the photo again",
  },
};

// When the check cannot name a material we would show (a mixed load, nothing recyclable, or a photo
// of a screen), there is nothing to name — so one line covers all of those.
const mismatchGeneric: Record<Lang, string> = {
  hi: "फ़ोटो आपके चुने हुए कबाड़ से मेल नहीं खा रही — सही चुनें या फिर से फ़ोटो लें",
  en: "This photo does not match the scrap you picked — pick the right one or take the photo again",
};

export const mismatchMaterials = Object.keys(mismatchByMaterial.en);

/** The sentence to show and speak when the photo check disagrees. */
export function mismatchVoice(lang: Lang, aiMaterial?: string | null): string {
  return (aiMaterial && mismatchByMaterial[lang][aiMaterial]) || mismatchGeneric[lang];
}

/** What the speaker button reads out on each screen. */
export const voice = {
  home: { hi: "नई बिक्री के लिए हरा बटन दबाएँ।", en: "Press the green button to make a new sale." },
  sale: {
    hi: "कबाड़ चुनें, वज़न खिसकाएँ, फिर फ़ोटो लेकर भेजें।",
    en: "Pick the scrap, slide to the weight, take a photo and send.",
  },
  waiting: { hi: "डीलर को अपना QR कार्ड दिखाएँ।", en: "Show your QR card to the dealer." },
  shop: { hi: "किस दुकान पर बेच रहे हैं?", en: "Which shop are you selling to?" },
};
