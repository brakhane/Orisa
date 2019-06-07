<template>
  <div>
    <button :class="'button is-primary' + (load ? ' is-loading' : '')" @click="p">Jajajojo</button>
    <div class="container">
      <b-table :data="data"  :loading="data.length == 0" :mobile-cards="false" :row-class="col">
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
            <span class="icon">
              <i class="mdi mdi-google-controller"  v-if="props.row.name.indexOf('1') == -1"></i>
              <i class="mdi mdi-google" v-else></i>
            </span>
            {{ props.row.name }}
          </b-table-column>
          <b-table-column field="W" label="W" numeric width="40" meta="Matches Won">
            {{ props.row.W }}
          </b-table-column>
          <b-table-column field="L" label="L" numeric width="40" meta="Matches Lost">
            {{ props.row.L }}
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

export default {
  name: 'test',
  props: [
    'foo'
  ],
  data () {
    return {
      load: false,
      data: [],
      columns: [
        {
          field: 'pos',
          label: '#',
          numeric: true,
          width: 40
        },
        {
          field: 'name',
          label: 'Name'
        },
        {
          field: 'points',
          label: 'Pts',
          numeric: true,
          width: 40
        },
        {
          field: 'W',
          label: 'W',
          numeric: true,
          width: 40
        },
        {
          field: 'L',
          label: 'L',
          numeric: true,
          width: 40
        }
      ]
    }
  },
  mounted () {
    setTimeout(() => {
      axios
        .get('http://localhost:8000/foo')
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
      return index < 1 ? 'leader' : index < 4 ? 'blubb' : ''
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
