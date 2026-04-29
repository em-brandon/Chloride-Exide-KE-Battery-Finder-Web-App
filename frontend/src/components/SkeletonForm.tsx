import { Skeleton } from '@/components/ui/Skeleton'

export function SkeletonForm() {
  return (
    <div className="space-y-4 animate-pulse" aria-label="Loading form…">
      <div className="space-y-1.5">
        <Skeleton className="h-4 w-12" />
        <Skeleton className="h-10 w-full" />
      </div>
      <div className="space-y-1.5">
        <Skeleton className="h-4 w-16" />
        <Skeleton className="h-10 w-full" />
      </div>
      <div className="space-y-1.5">
        <Skeleton className="h-4 w-8" />
        <Skeleton className="h-10 w-full" />
      </div>
      <Skeleton className="h-10 w-full mt-2" />
    </div>
  )
}
