import Link from "next/link"

export function SiteNav({ active }: { active: "demo" | "about" | "how-to-use" }) {
  const linkClass = (key: typeof active) =>
    `px-3 py-2 text-sm font-medium rounded-lg border transition-colors ${
      active === key
        ? "border-blue-300 bg-blue-50 text-blue-700"
        : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
    }`

  return (
    <header className="bg-white/80 backdrop-blur border-b border-gray-200 sticky top-0 z-10">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center justify-between gap-3">
        <Link href="/" className="flex items-center gap-2">
          <div className="flex items-center justify-center w-9 h-9 rounded-lg overflow-hidden bg-white border border-gray-200">
            <img src="/ottobiz.png" alt="Ottobiz Logo" className="w-full h-full object-contain" />
          </div>
          <span className="text-lg font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
            Ottobiz
          </span>
        </Link>
        <nav className="flex items-center gap-2">
          <Link href="/" className={linkClass("demo")}>
            Demo
          </Link>
          <Link href="/about" className={linkClass("about")}>
            About
          </Link>
          <Link href="/how-to-use" className={linkClass("how-to-use")}>
            How to use
          </Link>
        </nav>
      </div>
    </header>
  )
}
