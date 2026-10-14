function isTelegramUrl(value?: string | null): value is string {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:"
      && ["t.me", "www.t.me", "telegram.me", "www.telegram.me"].includes(url.hostname)
      && url.pathname.length > 1;
  } catch {
    return false;
  }
}

export function RadarIA({ telegramUrl }: { telegramUrl?: string | null }) {
  const telegramReady = isTelegramUrl(telegramUrl);

  return <aside className="radar-poster radar-poster-image" aria-label="Radar IA en Telegram">
    <div className="radar-poster-artwork">
      <img src="/radaria-telegram-poster.png" width="941" height="1672" decoding="async" alt="RadarIA: resumen diario de inteligencia artificial en Telegram." />
      {telegramReady ? <a className="radar-image-cta" href={telegramUrl} target="_blank" rel="noopener noreferrer">
        <span className="sr-only">Abrir Radaria IA en Telegram</span>
      </a> : <button className="radar-image-cta" type="button" disabled aria-disabled="true" title="Configura NEWS_TELEGRAM_URL para habilitar este enlace.">
        <span className="sr-only">Abrir Radaria IA en Telegram</span>
      </button>}
    </div>
  </aside>;
}
