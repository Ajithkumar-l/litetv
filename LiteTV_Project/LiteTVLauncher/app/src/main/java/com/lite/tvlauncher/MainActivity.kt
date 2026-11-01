package com.lite.tvlauncher

import android.app.Activity
import android.app.ActivityManager
import android.content.*
import android.content.pm.ResolveInfo
import android.graphics.drawable.Drawable
import android.net.ConnectivityManager
import android.os.*
import android.util.LruCache
import android.view.View
import android.view.ViewGroup
import android.widget.*
import java.util.concurrent.Executors

class AppItem(val pkg: String, val cls: String, val label: String, val ri: ResolveInfo)

class MainActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private val icons = LruCache<String, Drawable>(80)
    private var apps: List<AppItem> = emptyList()
    private var favSet: Set<String> = emptySet()
    private lateinit var prefs: SharedPreferences
    private lateinit var ramTxt: TextView; private lateinit var ramBar: ProgressBar
    private lateinit var stoTxt: TextView; private lateinit var stoBar: ProgressBar
    private lateinit var netTxt: TextView
    private val adapter = Adapter()
    private var dirty = true

    private val pkgReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context?, i: Intent?) { dirty = true; loadApps() }
    }
    private val tick = object : Runnable {
        override fun run() { updateStats(); ui.postDelayed(this, 5000) }
    }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        setContentView(R.layout.main)
        prefs = getSharedPreferences("fav", MODE_PRIVATE)
        ramTxt = findViewById(R.id.ramTxt); ramBar = findViewById(R.id.ramBar)
        stoTxt = findViewById(R.id.stoTxt); stoBar = findViewById(R.id.stoBar)
        netTxt = findViewById(R.id.netTxt)
        val grid = findViewById<GridView>(R.id.grid)
        grid.adapter = adapter
        grid.setOnItemClickListener { _, _, i, _ -> launch(apps[i]) }
        grid.setOnItemLongClickListener { _, _, i, _ -> toggleFav(apps[i].pkg); true }  // hold OK = favorite
        val f = IntentFilter(Intent.ACTION_PACKAGE_ADDED).apply { addAction(Intent.ACTION_PACKAGE_REMOVED); addDataScheme("package") }
        registerReceiver(pkgReceiver, f)
    }

    override fun onResume() {
        super.onResume()
        if (dirty) { dirty = false; loadApps() }
        ui.post(tick)
    }

    override fun onPause() { ui.removeCallbacks(tick); super.onPause() }
    override fun onDestroy() { unregisterReceiver(pkgReceiver); io.shutdown(); super.onDestroy() }
    override fun onBackPressed() {}  // home screen: Back does nothing

    private fun launch(a: AppItem) {
        try {
            startActivity(Intent(Intent.ACTION_MAIN).setComponent(ComponentName(a.pkg, a.cls)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: Exception) { Toast.makeText(this, "Can't open ${a.label}", Toast.LENGTH_SHORT).show() }
    }

    private fun toggleFav(pkg: String) {
        val s = HashSet(favSet); if (!s.add(pkg)) s.remove(pkg)
        prefs.edit().putStringSet("f", s).apply(); loadApps()
    }

    private fun loadApps() {
        io.execute {
            val pm = packageManager
            val fav = prefs.getStringSet("f", emptySet())!!.toSet()
            val seen = HashSet<String>(); val out = ArrayList<AppItem>()
            for (cat in arrayOf(Intent.CATEGORY_LEANBACK_LAUNCHER, Intent.CATEGORY_LAUNCHER)) {
                for (ri in pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(cat), 0)) {
                    val p = ri.activityInfo.packageName
                    if (p == packageName || !seen.add(p)) continue
                    out.add(AppItem(p, ri.activityInfo.name, ri.loadLabel(pm).toString(), ri))
                }
            }
            out.sortWith(compareBy({ !fav.contains(it.pkg) }, { it.label.lowercase() }))
            ui.post { favSet = fav; apps = out; adapter.notifyDataSetChanged() }
        }
    }

    private fun updateStats() {
        val mi = ActivityManager.MemoryInfo()
        (getSystemService(ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(mi)
        val used = mi.totalMem - mi.availMem
        val rp = (used * 100 / mi.totalMem).toInt()
        ramTxt.text = "RAM ${used shr 20} / ${mi.totalMem shr 20} MB · $rp%"; ramBar.progress = rp

        val s = StatFs(Environment.getDataDirectory().path)
        val tot = s.blockCountLong * s.blockSizeLong; val free = s.availableBlocksLong * s.blockSizeLong
        val sp = ((tot - free) * 100 / tot).toInt()
        stoTxt.text = "Storage ${gb(tot - free)} / ${gb(tot)} GB · $sp%"; stoBar.progress = sp

        @Suppress("DEPRECATION")
        val ni = (getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager).activeNetworkInfo
        @Suppress("DEPRECATION")
        netTxt.text = when {
            ni == null || !ni.isConnected -> "Offline"
            ni.type == ConnectivityManager.TYPE_WIFI -> "Wi-Fi connected"
            ni.type == ConnectivityManager.TYPE_ETHERNET -> "Ethernet"
            else -> "Online"
        }
    }

    private fun gb(b: Long) = String.format("%.1f", b / 1073741824.0)

    private inner class Adapter : BaseAdapter() {
        override fun getCount() = apps.size
        override fun getItem(i: Int) = apps[i]
        override fun getItemId(i: Int) = i.toLong()
        override fun getView(i: Int, v: View?, p: ViewGroup): View {
            val view = v ?: layoutInflater.inflate(R.layout.tile, p, false)
            val a = apps[i]
            val iv = view.findViewById<ImageView>(R.id.icon)
            view.findViewById<TextView>(R.id.label).text = (if (favSet.contains(a.pkg)) "★ " else "") + a.label
            iv.tag = a.pkg
            val cached = icons.get(a.pkg)
            if (cached != null) iv.setImageDrawable(cached) else {
                iv.setImageDrawable(null)
                io.execute {
                    val d = a.ri.loadIcon(packageManager); icons.put(a.pkg, d)
                    ui.post { if (iv.tag == a.pkg) iv.setImageDrawable(d) }
                }
            }
            return view
        }
    }
}
