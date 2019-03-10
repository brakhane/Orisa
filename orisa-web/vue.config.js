module.exports = {
  baseUrl: process.env.MY_BASE_URL,

  pages: {
    config: {
      entry: 'src/config_app_main.js',
      filename: 'config.html'
    },
    test: {
      entry: 'src/ttt/test.js',
      template: 'src/ttt/public/index.html',
      filename: 'test.html'
    }
  }
}
