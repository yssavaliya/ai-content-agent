# Content Strategy & Virality Engine

## Mission & Goal
Produce standalone high-impact visual posts that maximize viral reach, saves, and comments for `@aimagix.studio` on Instagram, continuously refining through real performance feedback via Buffer.

---

## 1. Visual Virality Architecture (Single-Post Format)
- **Aspect Ratio**: 1:1 square (1080x1080) optimized for feed prominence.
- **Visual Aesthetic**:
  - High-contrast, cinematic anime digital concept art.
  - Deep atmospheric color palettes: deep violet/obsidian backdrop, vibrant cyan neon blade beams, celestial blood moon / solar eclipse corona.
  - Lone hero silhouette compositions that trigger instant emotional intrigue in the first 0.5 seconds of scrolling.
- **Rule - Anti-Carousel Format**:
  - Single standalone poster visual ONLY. Never overlay pagination artifacts ("01/04", "Swipe Next >>", or multi-slide bullets) on the image.
  - Keep artwork clean, atmospheric, and museum-grade.

---

## 2. Copy & Caption Virality Formula
- **First 7 Words (The Scroll-Stopper Hook)**:
  - Open with a bold, philosophical, or counter-intuitive claim.
  - E.g.: *"The world only celebrates the awakening. They never see the ten thousand hours in the shadows."*
- **Body & Value Delivery**:
  - 3 concise bulleted insights formatted with clean spacing.
  - Resonate with creator discipline, craft mastery, and perseverance.
- **Call-to-Action (CTA)**:
  - Single, low-friction micro-action (emoji comment or save).
  - E.g.: *"Drop a ⚔️ in the comments if you are locking into your craft today!"*
- **Hashtag Matrix**:
  - 7 to 9 tightly curated hashtags mixing high-volume discovery (`#anime`, `#digitalart`) with niche affinity (`#animephilosophy`, `#visualstorytelling`, `#sololeveling`).

---

## 3. Continuous Learning & Mistake Correction Loop
1. **Pre-Generation Analytics Ingestion**:
   - Every scheduled pipeline run queries Buffer GraphQL API for recent post metrics (`impressions`, `reach`, `reactions/likes`, `comments`, `shares`, `saves`).
   - Persists performance data to `post_metrics` and `observations` in `agent.db`.
2. **Mistake Avoidance Engine**:
   - If a topic or hook receives below average engagement rate (< 2%), downgrade that topic category in subsequent candidate selections.
   - If an engagement driver (e.g. question CTA or neon katana visual) yields high saves (> 5% save-to-reach ratio), prioritize that visual motif in upcoming runs.
3. **Scientist Governance**:
   - Automatically track variant performance vs control benchmarks.
   - Promote winning elements into permanent strategy guidelines.
