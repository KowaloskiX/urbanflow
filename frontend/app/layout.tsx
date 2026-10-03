import type { Metadata } from 'next';
import { Geist, Geist_Mono, Urbanist } from 'next/font/google';
import './globals.css';
import './pitch.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

// Geometric and round like the logo's wordmark; used for headings only.
const urbanist = Urbanist({
  variable: '--font-display',
  subsets: ['latin', 'latin-ext'],
  weight: ['500', '600', '700'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'UrbanFlow — centrum operacyjne',
  description:
    'Mapa tramwajów na żywo i wsparcie decyzji dyspozytorskich dla Krakowa.',
  metadataBase: new URL(process.env.SITE_URL ?? 'http://localhost:5173'),
  openGraph: {
    title: 'UrbanFlow — centrum operacyjne',
    description: 'Tramwaje na żywo. Lepsze decyzje.',
    images: ['/og.png'],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'UrbanFlow — centrum operacyjne',
    description: 'Tramwaje na żywo. Lepsze decyzje.',
    images: ['/og.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pl">
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${urbanist.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
