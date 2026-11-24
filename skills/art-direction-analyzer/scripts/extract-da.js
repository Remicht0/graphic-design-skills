/**
 * Art Direction Analyzer — in-page extraction script.
 *
 * Run in the page context (browser JS tool, DevTools console, or Playwright's
 * page.evaluate). Paste the whole file; it evaluates to a JSON-serializable
 * object with the page's real computed design tokens:
 *   typography by role, fonts actually loaded, type scale, colors ranked by
 *   use (text / background / border), CSS custom properties, spacing scale,
 *   radii, shadows, layout systems, image treatments, motion (transitions,
 *   CSS animations, keyframes) and detected libraries / site builders.
 *
 * Computed styles are sampled (not source CSS) so the cascade, CSS variables
 * and JS-injected styles all resolve to final values.
 */
(() => {
  const MAX_ELEMENTS = 2500;
  const top = (obj, n) =>
    Object.entries(obj).sort((a, b) => b[1] - a[1]).slice(0, n).map(([value, count]) => ({ value, count }));
  const bump = (obj, k, w = 1) => { if (k !== undefined && k !== null && k !== '') obj[k] = (obj[k] || 0) + w; };

  const toHex = (c) => {
    const m = c && c.match(/rgba?\(([^)]+)\)/);
    if (!m) return c;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    const [r, g, b] = p;
    const a = p.length > 3 ? p[3] : 1;
    if (a === 0) return null;
    const hex = '#' + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('').toUpperCase();
    return a < 1 ? `${hex} @${Math.round(a * 100)}%` : hex;
  };

  // ---------------------------------------------------------------- CSS rules
  const cssVariables = {};
  const keyframes = new Set();
  const mediaQueries = {};
  const crossOriginSheets = [];
  const walkRules = (rules) => {
    for (const rule of rules) {
      if (rule.type === CSSRule.KEYFRAMES_RULE) keyframes.add(rule.name);
      if (rule.type === CSSRule.MEDIA_RULE) bump(mediaQueries, rule.conditionText || rule.media.mediaText);
      if (rule.style && rule.selectorText && /(^|,)\s*(:root|html|body)\b/.test(rule.selectorText)) {
        for (let i = 0; i < rule.style.length; i++) {
          const prop = rule.style[i];
          if (prop.startsWith('--') && Object.keys(cssVariables).length < 150) {
            cssVariables[prop] = rule.style.getPropertyValue(prop).trim();
          }
        }
      }
      if (rule.cssRules) walkRules(rule.cssRules);
    }
  };
  for (const sheet of document.styleSheets) {
    try { walkRules(sheet.cssRules); } catch (e) { crossOriginSheets.push(sheet.href); }
  }
  // also resolve variables declared on :root via computed style (works for cross-origin sheets)
  const rootCS = getComputedStyle(document.documentElement);
  for (let i = 0; i < rootCS.length; i++) {
    const prop = rootCS[i];
    if (prop.startsWith('--') && !(prop in cssVariables) && Object.keys(cssVariables).length < 150) {
      cssVariables[prop] = rootCS.getPropertyValue(prop).trim();
    }
  }

  // ---------------------------------------------------------------- fonts
  const loadedFonts = [];
  try {
    const seen = new Set();
    document.fonts.forEach((f) => {
      const key = `${f.family}|${f.weight}|${f.style}`;
      if (f.status === 'loaded' && !seen.has(key)) {
        seen.add(key);
        loadedFonts.push({ family: f.family.replace(/["']/g, ''), weight: f.weight, style: f.style });
      }
    });
  } catch (e) { /* older browsers */ }

  const typeStyle = (el) => {
    const cs = getComputedStyle(el);
    return {
      fontFamily: cs.fontFamily, fontSize: cs.fontSize, fontWeight: cs.fontWeight, fontStyle: cs.fontStyle,
      lineHeight: cs.lineHeight, letterSpacing: cs.letterSpacing, textTransform: cs.textTransform,
      color: toHex(cs.color), sample: (el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60),
    };
  };
  const roles = {
    h1: 'h1', h2: 'h2', h3: 'h3', body: 'main p, article p, p', small: 'small, figcaption, .caption',
    nav: 'nav a, header a', button: 'button, .btn, a.button, [role="button"]', label: 'label, .label, .eyebrow',
    footer: 'footer p, footer a',
  };
  const typographyByRole = {};
  for (const [role, sel] of Object.entries(roles)) {
    const el = [...document.querySelectorAll(sel)].find((e) => e.offsetParent !== null && (e.innerText || '').trim());
    if (el) typographyByRole[role] = typeStyle(el);
  }

  // ---------------------------------------------------------------- element walk
  const familyUse = {}, sizeUse = {}, weightUse = {}, lineHeights = {}, tracking = {};
  const textColors = {}, bgColors = {}, borderColors = {};
  const radii = {}, shadows = {}, spacing = {}, gaps = {};
  const transitions = {}, animations = {}, filters = {}, blends = {};
  const layout = { grid: 0, flex: 0, sticky: 0, fixed: 0, gridTemplates: {}, maxWidths: {} };
  let uppercase = 0, italic = 0, textEls = 0, gradients = 0, variableFont = 0;

  const els = document.querySelectorAll('body, body *');
  let n = 0;
  for (const el of els) {
    if (n++ >= MAX_ELEMENTS) break;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const hasText = [...el.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim().length > 1);
    if (hasText) {
      const len = Math.min(400, el.textContent.trim().length);
      textEls++;
      bump(familyUse, cs.fontFamily.split(',')[0].replace(/["']/g, '').trim(), len);
      bump(sizeUse, cs.fontSize, len);
      bump(weightUse, cs.fontWeight, len);
      bump(lineHeights, cs.lineHeight);
      if (cs.letterSpacing !== 'normal' && cs.letterSpacing !== '0px') bump(tracking, cs.letterSpacing);
      bump(textColors, toHex(cs.color), len);
      if (cs.textTransform === 'uppercase') uppercase++;
      if (cs.fontStyle === 'italic') italic++;
      if (cs.fontVariationSettings && cs.fontVariationSettings !== 'normal') variableFont++;
    }
    const bg = toHex(cs.backgroundColor);
    if (bg) {
      const r = el.getBoundingClientRect();
      bump(bgColors, bg, Math.max(1, Math.round((r.width * r.height) / 10000)));
    }
    if (cs.backgroundImage && cs.backgroundImage.includes('gradient')) gradients++;
    if (cs.borderTopWidth !== '0px' && cs.borderTopStyle !== 'none') bump(borderColors, toHex(cs.borderTopColor));
    if (cs.borderRadius && cs.borderRadius !== '0px') bump(radii, cs.borderRadius);
    if (cs.boxShadow && cs.boxShadow !== 'none') bump(shadows, cs.boxShadow);
    for (const p of ['paddingTop', 'paddingLeft', 'marginTop', 'marginBottom']) {
      const v = cs[p];
      if (v && v !== '0px' && !v.startsWith('-')) bump(spacing, v);
    }
    if (cs.rowGap && cs.rowGap !== 'normal' && cs.rowGap !== '0px') bump(gaps, cs.rowGap);
    if (cs.display.includes('grid')) {
      layout.grid++;
      if (cs.gridTemplateColumns && cs.gridTemplateColumns !== 'none') {
        bump(layout.gridTemplates, `${cs.gridTemplateColumns.split(' ').length} cols`);
      }
    }
    if (cs.display.includes('flex')) layout.flex++;
    if (cs.position === 'sticky') layout.sticky++;
    if (cs.position === 'fixed') layout.fixed++;
    if (cs.maxWidth && cs.maxWidth !== 'none' && cs.maxWidth.endsWith('px')) bump(layout.maxWidths, cs.maxWidth);
    if (cs.transitionDuration && cs.transitionDuration !== '0s') {
      bump(transitions, `${cs.transitionProperty} ${cs.transitionDuration} ${cs.transitionTimingFunction}`);
    }
    if (cs.animationName && cs.animationName !== 'none') {
      bump(animations, `${cs.animationName} ${cs.animationDuration} ${cs.animationTimingFunction} ${cs.animationIterationCount}`);
    }
    if (cs.filter && cs.filter !== 'none') bump(filters, cs.filter);
    if (cs.mixBlendMode && cs.mixBlendMode !== 'normal') bump(blends, cs.mixBlendMode);
  }

  // ---------------------------------------------------------------- media
  const imgs = [...document.images];
  const media = {
    images: imgs.length,
    videos: document.querySelectorAll('video').length,
    canvases: document.querySelectorAll('canvas').length,
    inlineSvgs: document.querySelectorAll('svg').length,
    objectFit: top(imgs.reduce((o, i) => (bump(o, getComputedStyle(i).objectFit), o), {}), 4),
    largestImages: imgs
      .map((i) => ({ src: (i.currentSrc || i.src || '').slice(0, 160), alt: (i.alt || '').slice(0, 80),
        w: Math.round(i.getBoundingClientRect().width), h: Math.round(i.getBoundingClientRect().height) }))
      .filter((i) => i.w * i.h > 0).sort((a, b) => b.w * b.h - a.w * a.h).slice(0, 6),
  };

  // ---------------------------------------------------------------- libraries & builders
  const has = (sel) => !!document.querySelector(sel);
  const scripts = [...document.scripts].map((s) => s.src || '').join(' ');
  const checks = {
    GSAP: () => !!window.gsap || /gsap/i.test(scripts),
    ScrollTrigger: () => !!window.ScrollTrigger,
    Lenis: () => !!window.Lenis || has('[data-lenis], html.lenis'),
    'Locomotive Scroll': () => !!window.LocomotiveScroll || has('[data-scroll-container]'),
    'Framer (site)': () => has('[data-framer-name], [data-framer-component-type]'),
    'Framer Motion': () => has('[style*="--framer"]'),
    Webflow: () => !!window.Webflow || has('html[data-wf-site]'),
    'Webflow IX2': () => has('[data-w-id]'),
    'Three.js': () => !!window.THREE || /three(\.min)?\.js/i.test(scripts),
    Spline: () => has('spline-viewer') || /spline/i.test(scripts),
    Rive: () => has('canvas[data-rive], rive-canvas') || /rive/i.test(scripts),
    Lottie: () => !!window.lottie || !!window.bodymovin || has('lottie-player, dotlottie-player'),
    Swiper: () => !!window.Swiper || has('.swiper'),
    Barba: () => !!window.barba || has('[data-barba]'),
    Swup: () => !!window.swup || has('[data-swup]'),
    'SplitType / Splitting': () => !!window.SplitType || !!window.Splitting || has('[data-splitting], .split-line'),
    AOS: () => !!window.AOS || has('[data-aos]'),
    p5: () => !!window.p5,
    Shopify: () => !!window.Shopify,
    WordPress: () => /wp-content|wp-includes/.test(document.documentElement.innerHTML.slice(0, 200000)),
    'Next.js': () => !!window.__NEXT_DATA__ || has('#__next'),
    Nuxt: () => !!window.__NUXT__ || has('#__nuxt'),
    Astro: () => has('astro-island'),
    Squarespace: () => !!window.Static && !!window.Static.SQUARESPACE_CONTEXT,
    Wix: () => has('[data-wix-id], #wix-viewer'),
    Cargo: () => /cargo\.site|cargocollective/.test(scripts),
    Tailwind: () => has('[class*="md:"], [class*="lg:"]'),
  };
  const libraries = Object.entries(checks).filter(([, f]) => { try { return f(); } catch (e) { return false; } }).map(([k]) => k);

  return {
    url: location.href,
    title: document.title,
    viewport: { width: innerWidth, height: innerHeight },
    pageHeight: document.documentElement.scrollHeight,
    typographyByRole,
    fonts: {
      loaded: loadedFonts.slice(0, 30),
      familiesByTextVolume: top(familyUse, 8),
      sizes: top(sizeUse, 14),
      weights: top(weightUse, 8),
      lineHeights: top(lineHeights, 8),
      letterSpacing: top(tracking, 8),
      uppercaseElements: uppercase, italicElements: italic, variableFontSettings: variableFont, textElements: textEls,
    },
    colors: {
      text: top(textColors, 10), backgrounds: top(bgColors, 10), borders: top(borderColors, 6), gradients,
    },
    cssVariables,
    spacing: { values: top(spacing, 14), gaps: top(gaps, 8) },
    shape: { radii: top(radii, 8), shadows: top(shadows, 5) },
    layout: { ...layout, gridTemplates: top(layout.gridTemplates, 6), maxWidths: top(layout.maxWidths, 6), mediaQueries: top(mediaQueries, 10) },
    motion: { transitions: top(transitions, 10), cssAnimations: top(animations, 10), keyframes: [...keyframes].slice(0, 30) },
    effects: { filters: top(filters, 6), blendModes: top(blends, 6) },
    media,
    libraries,
    crossOriginSheets: crossOriginSheets.filter(Boolean).slice(0, 10),
  };
})();
