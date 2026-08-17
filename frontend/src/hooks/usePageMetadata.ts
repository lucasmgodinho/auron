import { useEffect } from 'react'

export function usePageMetadata(title: string, description: string) {
  useEffect(() => {
    document.title = title === 'Auron' ? title : `${title} | Auron`
    const descriptionElement = document.querySelector<HTMLMetaElement>('meta[name="description"]')
    if (descriptionElement) descriptionElement.content = description
  }, [description, title])
}
