// lazyComponent — часть оболочки, которая грузится, только когда её показывают (28.10.2026).
//
// Окна и панели под v-if (шторка Вектора, активности, второй фактор на входе) лежали в
// главном чанке и удлиняли первую загрузку каждому, хотя открывает их меньшинство.
//
// Недоехавший чанк здесь не молчит (§4.33): одна повторная попытка на случай сети, потом
// та же дверь, что у ленивых страниц, — одна перезагрузка вкладки (код старше выложенного),
// а если и она не помогла — плашка «не удалось загрузить». `suspensible: false` — чтобы
// отказ не всплыл к ближайшему <Suspense> и не уронил страницу целиком.
//
// Прогрев: загрузчик попадает в список, который оболочка догружает в простое время вместе
// со страницами роли (utils/routePrefetch.js). Иначе service worker не положит чанк в кэш,
// и без сети шторка Вектора не открылась бы у того, кто ни разу её не открывал.
import { defineAsyncComponent } from 'vue'
import { isChunkLoadError, reloadOnceForChunk, showChunkFailure } from '@/utils/appVersion'

const WARM = []

/** warm: false — для того, что после первой отрисовки уже не понадобится (окна входа). */
export function lazyComponent(loader, { warm = true } = {}) {
  if (warm) WARM.push(loader)
  return defineAsyncComponent({
    loader,
    suspensible: false,
    onError(err, retry, fail, attempts) {
      if (attempts <= 1) { retry(); return }
      if (reloadOnceForChunk(err)) return
      if (isChunkLoadError(err)) showChunkFailure()
      fail()
    },
  })
}

/** Загрузчик в прогрев без компонента: для того, что объявлено внутри другого ленивого. */
export function warmAlso(loader) {
  WARM.push(loader)
}

/** Загрузчики для прогрева — копия, чтобы вызывающий не испортил список. */
export function warmLoaders() {
  return WARM.slice()
}
