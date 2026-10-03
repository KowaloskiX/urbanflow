'use client';

import { motion } from 'motion/react';

const SEGMENTS = 3;
const EMPTY_PLACE = '#dfe6e7';
const COLUMNS = 7;
const ROWS = 2;
const SEGMENT_WIDTH = 124;
const JOINT = 8;
const ORIGIN_X = 4;
const DOT_GAP = 15;
// Two doors per car, between the second/third and fifth/sixth places.
const DOOR_OFFSETS = [1.5, 4.5];

type Slot = { x: number; y: number; endDistance: number };

function segmentX(segment: number) {
  return ORIGIN_X + segment * (SEGMENT_WIDTH + JOINT);
}

function slotX(segment: number, column: number) {
  return segmentX(segment) + 17 + column * DOT_GAP;
}

const DOORS = Array.from({ length: SEGMENTS }, (_, segment) =>
  DOOR_OFFSETS.map((offset) => slotX(segment, offset)),
).flat();
const FIRST_X = slotX(0, 0);
const LAST_X = slotX(SEGMENTS - 1, COLUMNS - 1);

// The free places that remain sit at the very ends, by the cabs, where a full
// tram is emptiest — never as random holes in the middle.
const SLOTS: Slot[] = Array.from({ length: SEGMENTS * COLUMNS * ROWS }, (_, index) => {
  const segment = Math.floor(index / (COLUMNS * ROWS));
  const column = index % COLUMNS;
  const row = Math.floor(index / COLUMNS) % ROWS;
  const x = slotX(segment, column);
  return {
    x,
    y: 24 + row * 16,
    endDistance: Math.min(x - FIRST_X, LAST_X - x),
  };
}).sort((a, b) => b.endDistance - a.endDistance || a.y - b.y);

type TramFillProps = {
  passengers: number;
  capacity: number;
  color: string;
};

/** An articulated tram from above, its places filled in proportion to occupancy. */
export function TramFill({ passengers, capacity, color }: TramFillProps) {
  const filled = Math.min(SLOTS.length, Math.round((passengers / capacity) * SLOTS.length));
  const width = segmentX(SEGMENTS) - JOINT + ORIGIN_X;

  return (
    <svg className="tram-fill" viewBox={`0 0 ${width} 64`}>
      <title>{`Tramwaj z góry: ${passengers} z ${capacity} osób`}</title>
      {Array.from({ length: SEGMENTS - 1 }, (_, joint) => (
        <rect
          key={joint}
          x={segmentX(joint + 1) - JOINT}
          y="18"
          width={JOINT}
          height="28"
          rx="2"
          className="tram-fill-joint"
        />
      ))}
      {Array.from({ length: SEGMENTS }, (_, segment) => (
        <rect
          key={segment}
          x={segmentX(segment)}
          y="8"
          width={SEGMENT_WIDTH}
          height="48"
          rx={segment === 0 || segment === SEGMENTS - 1 ? 20 : 6}
          className="tram-fill-car"
        />
      ))}
      {DOORS.map((x) => (
        <rect key={x} x={x - 7} y="53" width="14" height="5" rx="1.5" className="tram-fill-door" />
      ))}
      {SLOTS.map((slot, index) => (
        // Places fill one after another when the card opens, in boarding order.
        <motion.circle
          key={`${slot.x}-${slot.y}`}
          cx={slot.x}
          cy={slot.y}
          r="4.5"
          className="tram-fill-place"
          initial={{ scale: 0.4, opacity: 0 }}
          animate={{ scale: 1, opacity: 1, fill: index < filled ? color : EMPTY_PLACE }}
          transition={{
            scale: { type: 'spring', duration: 0.4, bounce: 0.3, delay: index * 0.012 },
            opacity: { duration: 0.2, delay: index * 0.012 },
            fill: { duration: 0.3 },
          }}
          style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
        />
      ))}
    </svg>
  );
}
