'use client';

import Image from 'next/image';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { MotionConfig, motion, stagger, useScroll, useTransform } from 'motion/react';

import { BrandWordmark } from '@/components/brand-wordmark';
import { LiveCityMap } from '@/components/pitch/live-city-map';
import {
  AnimatedNumber,
  Reveal,
  RevealGroup,
  TickerNumber,
  itemVariants,
} from '@/components/motion-primitives';
import { API_BASE } from '@/lib/api';

type NetworkStats = {
  trams: number;
  buses: number;
};

type VehicleSummary = {
  vehicleMode: 'TRAM' | 'BUS';
  isSimulation: boolean;
};

const STATS_REFRESH_MS = 10_000;

function useNetworkStats() {
  const [stats, setStats] = useState<NetworkStats | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch(`${API_BASE}/vehicles`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const { vehicles } = (await response.json()) as {
          vehicles: VehicleSummary[];
        };
        const real = vehicles.filter((vehicle) => !vehicle.isSimulation);
        if (cancelled) return;
        setStats({
          trams: real.filter((vehicle) => vehicle.vehicleMode === 'TRAM').length,
          buses: real.filter((vehicle) => vehicle.vehicleMode === 'BUS').length,
        });
      } catch {
        if (!cancelled) setStats(null);
      }
    };
    void load();
    const interval = window.setInterval(() => void load(), STATS_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  return stats;
}

/** The navigation sits on the hero video until the page scrolls past it. */
function useScrolledPast(offset: number) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const update = () => setScrolled(window.scrollY > offset);
    update();
    window.addEventListener('scroll', update, { passive: true });
    return () => window.removeEventListener('scroll', update);
  }, [offset]);

  return scrolled;
}

type SensorReadings = { fps: number; readings: [number, number, number][] };

/**
 * The counter's real per-frame output for the hero clip, kept in step with the
 * video. Shown as HTML rather than burned into the frames, so it stays sharp and
 * is never cropped by the video's cover fit.
 */
function SensorReadout({
  video,
  src = '/video/door-sensor.json',
  labels = ['Wsiadło', 'Wysiadło'],
  className = 'readout',
}: {
  video: React.RefObject<HTMLVideoElement | null>;
  src?: string;
  labels?: [string, string];
  className?: string;
}) {
  const [data, setData] = useState<SensorReadings | null>(null);
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void fetch(src)
      .then((response) =>
        response.ok ? (response.json() as Promise<SensorReadings>) : null,
      )
      .then((json) => {
        if (!cancelled) setData(json);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [src]);

  useEffect(() => {
    if (!data) return;
    let handle = 0;
    const tick = () => {
      const element = video.current;
      if (element) {
        const index = Math.min(
          data.readings.length - 1,
          Math.floor(element.currentTime * data.fps),
        );
        setFrame((current) => (current === index ? current : index));
      }
      handle = window.requestAnimationFrame(tick);
    };
    handle = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(handle);
  }, [data, video]);

  if (!data) return <span className={className} />;
  const [boarded, alighted] = data.readings[frame] ?? [0, 0, 0];
  return (
    <span className={className} aria-live="off">
      <TickerNumber value={boarded} /> {labels[0].toLowerCase()} ·{' '}
      <TickerNumber value={alighted} /> {labels[1].toLowerCase()}
    </span>
  );
}

const steps = [
  {
    title: 'Kamera nad drzwiami liczy wejścia i wyjścia',
    body: 'Model wykrywa ludzi i śledzi każdego przez próg. Przejście przez linię to +1 albo −1.',
    meta: 'RT-DETR, liczenie na urządzeniu w wagonie',
  },
  {
    title: 'Mapa pokazuje zapełnienie każdego tramwaju',
    body: 'Pozycje pochodzą z otwartego feedu ZTP Kraków. Do każdego tramwaju z licznikiem dopisujemy liczbę pasażerów.',
    meta: 'GTFS-Realtime co 5 s',
  },
  {
    title: 'System proponuje dodatkowy kurs',
    body: 'Gdy tramwaj jest pełny przez dwie minuty, dyspozytor dostaje gotową propozycję rezerwy na tej linii. Decyzję podejmuje człowiek.',
    meta: 'Próg: 85% zapełnienia przez 2 min',
  },
];

const storyBeats = [
  { time: '0:00', text: 'Tramwaj linii 13 ma 186 osób na 202 miejsca.' },
  { time: '2:00', text: 'Tłok trwa dwie minuty — przychodzi rekomendacja.' },
  { time: '2:05', text: 'Dyspozytor wysyła rezerwę jednym kliknięciem.' },
];

const nextSteps = [
  {
    title: 'Model douczony na nagraniach z wagonów',
    body: 'Dziś to ogólny detektor ludzi. Kamera z sufitu tramwaju potrzebuje własnych danych.',
  },
  {
    title: 'Decyzje oparte na danych zamiast stałych',
    body: 'Prawdziwy odstęp do następnego kursu i stan rezerw w zajezdniach.',
  },
  {
    title: 'Prognoza tłoku',
    body: 'Historia przejazdów pozwoli wysłać rezerwę, zanim tramwaj się zapełni.',
  },
];

const MotionLink = motion.create(Link);

function PillLink({
  href,
  children,
  tone = 'light',
}: {
  href: string;
  children: React.ReactNode;
  tone?: 'light' | 'dark';
}) {
  return (
    <MotionLink
      href={href}
      className={`pill ${tone}`}
      whileTap={{ scale: 0.97 }}
      transition={{ duration: 0.12 }}
    >
      {children}
      <span className="pill-arrow" aria-hidden="true">
        <ArrowRight />
      </span>
    </MotionLink>
  );
}

/**
 * The product recording in a browser window that starts tilted back in 3D and
 * straightens up as it scrolls into view.
 */
function TiltedBrowser() {
  const frame = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: frame, offset: ['start end', 'center center'] });
  const rotateX = useTransform(scrollYProgress, [0, 1], [24, 0]);
  const scale = useTransform(scrollYProgress, [0, 1], [0.88, 1]);
  const y = useTransform(scrollYProgress, [0, 1], [80, 0]);
  const glow = useTransform(scrollYProgress, [0, 1], [0, 1]);

  return (
    <div ref={frame} className="tilt-stage">
      <motion.div className="tilt-glow" style={{ opacity: glow }} aria-hidden="true" />
      <motion.figure className="tilt-browser" style={{ rotateX, scale, y }}>
        <div className="tilt-chrome" aria-hidden="true">
          <span className="tilt-dots"><i /><i /><i /></span>
          <span className="tilt-url">urbanflow · mapa na żywo</span>
        </div>
        <video
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          poster="/video/dispatch-story.jpg"
          aria-label="Nagranie mapy: przepełniony tramwaj, rekomendacja i wysłanie rezerwy"
        >
          <source src="/video/dispatch-story.mp4" type="video/mp4" />
        </video>
      </motion.figure>
    </div>
  );
}

export function PitchPage() {
  const stats = useNetworkStats();
  const scrolled = useScrolledPast(80);
  const heroVideo = useRef<HTMLVideoElement>(null);

  // Reduced motion: keep the poster frame instead of a looping video.
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      heroVideo.current?.pause();
    }
  }, []);

  return (
    <MotionConfig reducedMotion="user">
    <div className="pitch">
      <header className={`pitch-nav${scrolled ? ' solid' : ''}`}>
        <Link href="/" className="pitch-brand" aria-label="UrbanFlow">
          <BrandWordmark size={28} tone={scrolled ? 'dark' : 'light'} />
        </Link>
        <nav aria-label="Sekcje">
          <a href="#jak-to-dziala">Jak to działa</a>
          <a href="#demo">Demo</a>
          <a href="#prywatnosc">Prywatność</a>
        </nav>
        <PillLink href="/mapa" tone={scrolled ? 'dark' : 'light'}>
          Mapa na żywo
        </PillLink>
      </header>

      <section className="pitch-hero">
        <video
          ref={heroVideo}
          className="pitch-hero-video"
          autoPlay
          muted
          loop
          playsInline
          preload="auto"
          poster="/video/door-sensor.jpg"
          aria-hidden="true"
        >
          <source src="/video/door-sensor.mp4" type="video/mp4" />
        </video>
        <div className="pitch-hero-shade" />
        <motion.div
          className="pitch-hero-content"
          initial="hidden"
          animate="shown"
          variants={{ hidden: {}, shown: { transition: { delayChildren: stagger(0.1, { startDelay: 0.15 }) } } }}
        >
          <motion.h1 variants={itemVariants}>Widzimy, który tramwaj jest pełny.</motion.h1>
          <motion.p variants={itemVariants}>
            Kamera nad drzwiami liczy pasażerów, mapa pokazuje zapełnienie
            tramwajów w Krakowie, a dyspozytor wie, gdzie wysłać dodatkowy kurs.
          </motion.p>
          <motion.div variants={itemVariants}>
            <PillLink href="/mapa">Otwórz mapę na żywo</PillLink>
          </motion.div>
        </motion.div>
        <div className="pitch-hero-caption">
          <p>
            Odczyt modelu na tym nagraniu: <SensorReadout video={heroVideo} />
          </p>
          <p>Nagranie: SHOX ART / Pexels, Wrocław</p>
        </div>
      </section>

      <section className="pitch-statement">
        <Reveal className="pitch-container pitch-statement-grid">
          <h2>
            <span className="line">
              W Krakowie jeździ teraz{' '}
              <span className="nowrap">
                {stats ? (
                  <>
                    <AnimatedNumber value={stats.trams} duration={1.2} /> tramwajów
                  </>
                ) : (
                  'ponad sto tramwajów'
                )}
              </span>
              .
            </span>
            <span className="line">Dyspozytor wie, gdzie jest każdy z nich.</span>
            <span className="line">Nie wie, ilu ludzi jest w środku.</span>
          </h2>
          <p>
            UrbanFlow dodaje do mapy brakującą informację: zapełnienie policzone
            kamerą nad drzwiami. Pozycje na żywo z otwartego feedu ZTP Kraków.
          </p>
        </Reveal>
      </section>

      <section className="pitch-section" id="jak-to-dziala">
        <div className="pitch-container">
          <Reveal className="pitch-steps-head">
            <h2>Jak to działa</h2>
            <p>Od kamery w wagonie do decyzji dyspozytora, w trzech krokach.</p>
          </Reveal>
          <RevealGroup as="ol" className="pitch-steps">
            {steps.map((step, index) => (
              <motion.li key={step.title} variants={itemVariants}>
                <span className="pitch-step-index">0{index + 1}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
                <small>{step.meta}</small>
              </motion.li>
            ))}
          </RevealGroup>
        </div>
      </section>

      <section className="pitch-cabin">
        <div className="pitch-container">
          <Reveal className="pitch-cabin-head">
            <h2>Kamery w środku pojazdu</h2>
            <p>
              Ten sam model na czterech kamerach pod sufitem autobusu miejskiego.
              Liczy pasażerów w każdym widoku i zauważa wózek inwalidzki, gdy ten
              wjeżdża do pojazdu.
            </p>
          </Reveal>
          <motion.figure
            className="pitch-cabin-frame"
            initial={{ opacity: 0, y: 24 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-120px' }}
            transition={{ duration: 0.8, ease: [0.23, 1, 0.32, 1] }}
          >
            <video
              autoPlay
              muted
              loop
              playsInline
              preload="metadata"
              poster="/video/bus-multicam.jpg"
              aria-label="Cztery kamery pod sufitem autobusu z ramkami wokół pasażerów i wózka inwalidzkiego"
            >
              <source src="/video/bus-multicam.mp4" type="video/mp4" />
            </video>
            <figcaption>
              Scena inscenizowana w autobusie testowym, kilka osób. Kolejny krok:
              nagrania z kamer w krakowskich tramwajach w godzinach szczytu.
              Nagranie: TU Berlin / MAN Truck &amp; Bus, CC BY 4.0.
            </figcaption>
          </motion.figure>
        </div>
      </section>

      <section className="pitch-space">
        <div className="pitch-container">
          <Reveal className="pitch-space-head">
            <h2>Liczymy miejsce, nie tylko głowy</h2>
            <p>
              Kamera w wagonie widzi też wózki i rowery. Wózek inwalidzki zajmuje
              podłogę kilku stojących osób, więc tramwaj z dwoma wózkami jest pełny
              wcześniej, niż pokazuje sama liczba pasażerów. A osoba na wózku może
              sprawdzić, czy w nadjeżdżającym tramwaju jest dla niej miejsce.
            </p>
          </Reveal>
          <RevealGroup className="space-grid">
            <motion.figure className="space-card wide" variants={itemVariants}>
              <Image
                src="/img/cabin-aids.jpg"
                alt="Wnętrze autobusu: model zaznaczył wózek dziecięcy, wózek inwalidzki i cztery osoby"
                width={799}
                height={533}
                sizes="(max-width: 900px) 100vw, 60vw"
              />
              <figcaption>
                <p className="space-sum">
                  <span>4 osoby</span>
                  <span className="plus stroller">wózek dziecięcy +1,5</span>
                  <span className="plus wheelchair">wózek inwalidzki +2</span>
                  <strong>= 7,5 miejsca</strong>
                </p>
                <small>
                  Fot. Metropolitan Transportation Authority, CC BY 2.0 · ramki: model
                  UrbanFlow
                </small>
              </figcaption>
            </motion.figure>
            <motion.figure className="space-card" variants={itemVariants}>
              <Image
                src="/img/cabin-bike.jpg"
                alt="Rower oparty o siedzenia w wagonie, zaznaczony przez model"
                width={1600}
                height={1189}
                sizes="(max-width: 900px) 100vw, 35vw"
              />
              <figcaption>
                <p className="space-sum">
                  <span className="plus bicycle">rower +1,5</span>
                </p>
                <small>Fot. citytransportinfo, CC0 · ramki: model UrbanFlow</small>
              </figcaption>
            </motion.figure>
          </RevealGroup>
        </div>
      </section>

      <section className="pitch-demo" id="demo">
        <div className="pitch-container">
          <Reveal className="pitch-demo-head">
            <h2>Od tłoku do decyzji w dwie minuty</h2>
            <p>
              Nagranie naszej mapy na żywo. Pozycje tramwajów są prawdziwe, tłok
              na jednym z nich jest symulowany.
            </p>
          </Reveal>
          <TiltedBrowser />
          <RevealGroup as="ol" className="pitch-beats">
            {storyBeats.map((beat) => (
              <motion.li key={beat.time} variants={itemVariants}>
                <time>{beat.time}</time>
                <p>{beat.text}</p>
              </motion.li>
            ))}
          </RevealGroup>
        </div>
      </section>

      <section className="pitch-section" id="prywatnosc">
        <div className="pitch-container pitch-split">
          <Reveal>
            <h2>Obraz nie opuszcza tramwaju</h2>
            <p className="pitch-section-lead">
              Model działa na urządzeniu w wagonie. Do serwera trafia tylko takie
              zdarzenie — bez zdjęć, twarzy i nagrań.
            </p>
          </Reveal>
          <Reveal delay={0.1}>
          <pre className="pitch-payload" aria-label="Przykładowe zdarzenie wysyłane do serwera">{`{
  "eventId": "run-7:door-2:41",
  "direction": "boarding",
  "passengers": 1,
  "observedAt": "2026-10-03T08:14:03Z"
}`}</pre>
          </Reveal>
        </div>
      </section>

      <section className="pitch-section muted">
        <div className="pitch-container pitch-split">
          <Reveal>
            <h2>Co dalej</h2>
            <p className="pitch-section-lead">
              Prototyp działa od kamery do decyzji. Kolejne kroki:
            </p>
          </Reveal>
          <RevealGroup as="ul" className="pitch-rows plain">
            {nextSteps.map((item) => (
              <motion.li key={item.title} variants={itemVariants}>
                <div>
                  <h3>{item.title}</h3>
                  <p>{item.body}</p>
                </div>
              </motion.li>
            ))}
          </RevealGroup>
        </div>
      </section>

      <section className="pitch-final">
        <LiveCityMap />
        <div className="pitch-final-shade" />
        <div className="pitch-container pitch-final-inner">
          <Reveal className="pitch-final-copy">
            <span className="pitch-live-badge">
              <span className="pitch-live-dot" aria-hidden="true" /> To nie jest nagranie
            </span>
            <h2>Kraków, w tej chwili.</h2>
            <p>
              Każda kropka to tramwaj albo autobus z feedu ZTP, przesuwający się na
              żywo. Pełne tramwaje pulsują na czerwono.
            </p>
            {stats && (
              <dl className="pitch-final-stats">
                <div>
                  <dt>Tramwaje</dt>
                  <dd><AnimatedNumber value={stats.trams} duration={1.2} /></dd>
                </div>
                <div>
                  <dt>Autobusy</dt>
                  <dd><AnimatedNumber value={stats.buses} duration={1.2} /></dd>
                </div>
              </dl>
            )}
            <PillLink href="/mapa">Otwórz mapę na żywo</PillLink>
          </Reveal>
        </div>
      </section>

      <footer className="pitch-footer">
        <div className="pitch-container">
          <span>UrbanFlow · prototyp</span>
          <span>Pozycje pojazdów: ZTP Kraków, GTFS-Realtime · Wideo: SHOX ART / Pexels</span>
        </div>
      </footer>
    </div>
    </MotionConfig>
  );
}
