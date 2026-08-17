import { usePreferences } from '../preferences/usePreferences'

type BrandLogoProps = {
  variant: 'horizontal' | 'vertical' | 'mark'
  scheme?: 'auto' | 'light' | 'dark'
  eager?: boolean
}

const dimensions = {
  horizontal: { width: 400, height: 100, name: 'logo' },
  vertical: { width: 480, height: 480, name: 'brand' },
  mark: { width: 96, height: 96, name: 'mark' },
} as const

export function BrandLogo({ variant, scheme = 'auto', eager = false }: BrandLogoProps) {
  const { resolvedTheme } = usePreferences()
  const asset = dimensions[variant]
  const assetScheme = scheme === 'auto' ? resolvedTheme : scheme

  return (
    <img
      className={`brand-logo brand-logo-${variant}`}
      src={`/auron-${asset.name}-${assetScheme}.png`}
      width={asset.width}
      height={asset.height}
      alt="Auron"
      loading={eager ? 'eager' : 'lazy'}
      fetchPriority={eager ? 'high' : 'auto'}
      decoding="async"
    />
  )
}
