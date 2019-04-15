<template>
  <div>
    <button :class="'button is-primary' + (load ? ' is-loading' : '')" @click="p">Jajajojo</button>
    <div class="container">
      <b-table v-sortable="sortableOptions" :data="data"  :loading="data.length == 0" :mobile-cards="false" :row-class="col">
        <template slot-scope="props" slot="header">
          <b-tooltip :active="!!props.column.meta" :label="props.column.meta" dashed>
            {{ props.column.label }}
          </b-tooltip>
        </template>
        <template slot-scope="props">
          <b-table-column field="pos" custom-key="#" numeric width="40">
            {{ props.row.pos }}
          </b-table-column>
          <b-table-column field="name" custom-key="Name">
            <!-- div style="width: 32px; height: 32px; display:inline-block">I</div -->
            <img src="https://bnetcmsus-a.akamaihd.net/cms/page_media/E9MU0AK0JIXT1507858876249.svg" width="32" height="32">
            <span>
              {{ props.row.name }}
            </span>
          </b-table-column>
          <b-table-column field="W" label="W" numeric width="40" meta="Matches Won">
            {{ props.row.W }}
          </b-table-column>
          <b-table-column field="L" label="L" numeric width="40" meta="Matches Lost">
            {{ props.row.L }}
          </b-table-column>
          <b-table-column field="F" label="MS" numeric width="40" meta="Map Scores">
            {{ props.row.F }}:{{ props.row.A }}
          </b-table-column>
          <b-table-column field="F" label="MD" numeric width="40" meta="Map Difference">
            {{ (props.row.F > props.row.A ? "+" : "") + (props.row.F - props.row.A) }}
          </b-table-column>
          <b-table-column field="points" label="Pts" numeric width="40" meta="Points">
            {{ props.row.points }}
          </b-table-column>
        </template>
        <template slot="empty">EMPTY</template>
      </b-table>
    </div>
  </div>

</template>
<script>

import axios from 'axios'
import Sortable from 'sortablejs'

const createSortable = (el, options, vnode) => {
  return Sortable.create(el, {
    ...options,
    onEnd: function (evt) {
      const data = vnode.context.data
      const item = data[evt.oldIndex]
      if (evt.newIndex > evt.oldIndex) {
        for (let i = evt.oldIndex; i < evt.newIndex; i++) {
          data[i] = data[i + 1]
        }
      } else {
        for (let i = evt.oldIndex; i > evt.newIndex; i--) {
          data[i] = data[i - 1]
        }
      }
      data[evt.newIndex] = item
      vnode.context.$toast.open(`Moved ${item.name} from row ${evt.oldIndex + 1} to ${evt.newIndex + 1}`)
    }
  })
}


const sortable = {
  name: 'sortable',
  bind (el, binding, vnode) {
    const table = el.querySelector('table')
    table._sortable = createSortable(table.querySelector('tbody'), binding.value, vnode)
  },
  update (el, binding, vnode) {
    const table = el.querySelector('table')
    table._sortable.destroy()
    table._sortable = createSortable(table.querySelector('tbody'), binding.value, vnode)
  },
  unbind (el) {
    const table = el.querySelector('table')
    table._sortable.destroy()
  }
}

export default {
  name: 'test',
  directives: { sortable },
  props: [
    'foo'
  ],
  data () {
    return {
      sortableOptions: {
        chosenClass: 'is-selected',
        animation: 75
      },
      load: false,
      data: [],
      columns: [
        {
          field: "pos",
          label: "#",
          numeric: true,
          width: 40
        },
        {
          field: "name",
          label: "Name",
        },
        {
          field: "points",
          label: "Pts",
          numeric: true,
          width: 40
        },
        {
          field: "W",
          label: "W",
          numeric: true,
          width: 40
        },
        {
          field: "L",
          label: "L",
          numeric: true,
          width: 40
        }
      ]
    }
  },
  mounted () {
    setTimeout(() => {
      axios
        .get("http://localhost:8000/foo")
        .then(resp => {
          var prevPoints = -1
          this.data = resp.data.map((row, i) => {
            row.pos = prevPoints !== row.points ? i + 1 : null
            prevPoints = row.points
            
            return row
          })
        })
    }, 200)
  },
  methods: {
    p () {
      this.load = true
    },
    col (row, index) {
      return index < 1 ? "leader" : index < 4 ? "blubb" : ""
    }
  }
}

</script>

<style lang="scss">
@import "~bulma/sass/utilities/_all";
.leader {
  $x: rgb(46, 90, 161);
  background-color: $x;
  color: findColorInvert($x);
}
.blubb {
  $x: rgba(41, 209, 11, 0.4);
  background-color: $x;
  color: $black;
}
table a {
  color: inherit;
}
</style>
