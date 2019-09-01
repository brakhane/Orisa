<template>
  <div v-html="compiledMarkdown"></div>
</template>

<script>
import marked from 'marked'

export default {
  props: {
    source: { default: '', type: String },
    anchorAttributes: { default: () => {}, type: Object }
  },
  computed: {
    compiledMarkdown () {
      let html = marked(this.source, { breaks: true })

      let htmlDoc = new DOMParser().parseFromString(html, 'text/html')

      htmlDoc.querySelectorAll('a').forEach(element => {
        Object.keys(this.anchorAttributes).map((attr) => {
          element.setAttribute(attr, this.anchorAttributes[attr])
        })
      })

      return htmlDoc.querySelector('body').innerHTML
    }
  }
}
</script>
