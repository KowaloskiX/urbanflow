'use client';

import { useEffect } from 'react';
import {
  animate,
  motion,
  stagger,
  useMotionValue,
  useTransform,
  type HTMLMotionProps,
  type Transition,
} from 'motion/react';

/** Strong ease-out: starts fast, so the interface feels like it answered at once. */
export const EASE_OUT = [0.23, 1, 0.32, 1] as const;

export const spring: Transition = { type: 'spring', duration: 0.45, bounce: 0.12 };

/** Card-sized enter/exit: a short rise with a touch of scale, never from nothing. */
export const cardMotion = {
  initial: { opacity: 0, y: -10, scale: 0.97 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -6, scale: 0.98, transition: { duration: 0.15 } },
  transition: spring,
};

type RevealProps = HTMLMotionProps<'div'> & { delay?: number };

/** Fades a block up once, when it first scrolls into view. */
export function Reveal({ delay = 0, children, ...props }: RevealProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ duration: 0.7, ease: EASE_OUT, delay }}
      {...props}
    >
      {children}
    </motion.div>
  );
}

const groupVariants = {
  hidden: {},
  shown: { transition: { delayChildren: stagger(0.07) } },
};

export const itemVariants = {
  hidden: { opacity: 0, y: 16 },
  shown: { opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE_OUT } },
};

/** A list whose children reveal one after another; pair with `itemVariants`. */
export function RevealGroup({
  as = 'div',
  children,
  className,
}: {
  as?: 'div' | 'ol' | 'ul';
  children: React.ReactNode;
  className?: string;
}) {
  const Component = motion[as];
  return (
    <Component
      className={className}
      variants={groupVariants}
      initial="hidden"
      whileInView="shown"
      viewport={{ once: true, margin: '-80px' }}
    >
      {children}
    </Component>
  );
}

/** A number that glides to its new value instead of jumping. */
export function AnimatedNumber({ value, duration = 0.6 }: { value: number; duration?: number }) {
  const motionValue = useMotionValue(value);
  const rounded = useTransform(motionValue, (latest) => Math.round(latest).toString());

  useEffect(() => {
    const controls = animate(motionValue, value, { duration, ease: EASE_OUT });
    return () => controls.stop();
  }, [duration, motionValue, value]);

  return <motion.span style={{ fontVariantNumeric: 'tabular-nums' }}>{rounded}</motion.span>;
}

/** A counter digit that rolls in from above when it changes, like a departure board. */
export function TickerNumber({ value }: { value: number }) {
  return (
    <span className="ticker">
      <motion.span
        key={value}
        initial={{ y: '-60%', opacity: 0 }}
        animate={{ y: '0%', opacity: 1 }}
        transition={spring}
      >
        {value}
      </motion.span>
    </span>
  );
}
