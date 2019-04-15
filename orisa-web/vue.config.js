module.exports = {
  publicPath: process.env.MY_BASE_URL,

  pages: {
    config: {
      entry: 'guild_config/main.js',
      filename: 'config.html'
    },
    test: {
      entry: 'tournament/main.js',
      filename: 'test.html'
    }
  }
}
