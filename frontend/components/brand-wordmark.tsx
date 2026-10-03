import Image from 'next/image';

type BrandWordmarkProps = {
  size?: number;
  /** `light` for dark backgrounds such as the hero video: the navy turns white. */
  tone?: 'dark' | 'light';
};

/** The logo as a horizontal lockup: tram mark, then "urban" in navy and "flow" in teal. */
export function BrandWordmark({ size = 32, tone = 'dark' }: BrandWordmarkProps) {
  return (
    <span className={`brand-wordmark ${tone}`}>
      <Image src="/mark.svg" alt="" width={Math.round(size * 1.46)} height={size} priority />
      <span className="brand-wordmark-text" aria-label="UrbanFlow">
        urban<span>flow</span>
      </span>
    </span>
  );
}
